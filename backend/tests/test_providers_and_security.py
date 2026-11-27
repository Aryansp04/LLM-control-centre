"""Unit tests for Multi-Provider Adapters, Retries, Encryption, Pricing, Attachments, and Context."""

from __future__ import annotations

import base64
import json
import logging
from decimal import Decimal

import httpx
import pytest

from app.core.errors import AppError
from app.core.security import (
    SecretRedactionFilter,
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
    redact_secrets,
)
from app.models.entities import Message
from app.providers.anthropic_adapter import AnthropicAdapter
from app.providers.gemini_adapter import GeminiAdapter
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.registry import ProviderRegistry
from app.providers.types import (
    ChatMessageInput,
    GenerationRequest,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from app.services.attachments import validate_and_process_attachment
from app.services.context_manager import build_managed_context
from app.services.pricing import calculate_estimated_cost


@pytest.mark.asyncio
async def test_openai_adapter_streaming_and_reasoning_capabilities():
    captured_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(body)
        sse_lines = (
            'data: {"id":"chatcmpl-1","model":"o3-mini-2025-01-31","choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"id":"chatcmpl-1","model":"o3-mini-2025-01-31","choices":[{"delta":{"content":" world"},"finish_reason":"stop"}]}\n\n'
            'data: {"id":"chatcmpl-1","model":"o3-mini-2025-01-31","choices":[],"usage":{"prompt_tokens":14,"completion_tokens":2}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_lines.encode("utf-8"),
        )

    adapter = OpenAIAdapter(http_transport=httpx.MockTransport(handler))
    req = GenerationRequest(
        model="o3-mini",
        messages=[ChatMessageInput(role="user", content="Say hello")],
        system_instruction="Be concise",
        temperature=0.8,  # Should be omitted automatically for reasoning model o3-mini!
        max_output_tokens=256,
    )

    chunks = [c async for c in adapter.stream(req, "sk-test-openai-key")]
    text = "".join(c.delta_text for c in chunks)
    final = chunks[-1]

    assert text == "Hello world"
    assert final.is_final is True
    assert final.actual_model == "o3-mini-2025-01-31"
    assert final.input_tokens == 14
    assert final.output_tokens == 2

    sent = captured_payloads[0]
    assert "temperature" not in sent
    assert sent["max_completion_tokens"] == 256
    assert sent["messages"][0]["role"] == "developer"


@pytest.mark.asyncio
async def test_gemini_adapter_streaming_and_header_key_isolation():
    seen_urls = []
    seen_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        seen_headers.append(dict(request.headers))
        sse_data = (
            'data: {"candidates":[{"content":{"parts":[{"text":"Gemini "}],"role":"model"}}],"modelVersion":"gemini-2.5-flash-001"}\n\n'
            'data: {"candidates":[{"content":{"parts":[{"text":"live!"}],"role":"model"},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":9,"candidatesTokenCount":3},"modelVersion":"gemini-2.5-flash-001"}\n\n'
        )
        return httpx.Response(200, content=sse_data.encode("utf-8"))

    adapter = GeminiAdapter(http_transport=httpx.MockTransport(handler))
    req = GenerationRequest(
        model="gemini-2.5-flash",
        messages=[ChatMessageInput(role="user", content="Ping")],
        system_instruction="Respond briefly",
        temperature=0.4,
        max_output_tokens=128,
    )

    chunks = [c async for c in adapter.stream(req, "AIzaTestSecretKey123456789")]
    assert "".join(c.delta_text for c in chunks) == "Gemini live!"
    assert chunks[-1].actual_model == "gemini-2.5-flash-001"
    assert chunks[-1].input_tokens == 9
    assert chunks[-1].output_tokens == 3
    # Ensure secret key is NEVER placed in query string
    assert "AIzaTestSecretKey" not in seen_urls[0]
    assert seen_headers[0]["x-goog-api-key"] == "AIzaTestSecretKey123456789"


@pytest.mark.asyncio
async def test_anthropic_adapter_streaming_and_temperature_clamping():
    captured_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = json.loads(request.content.decode("utf-8"))
        sse = (
            'event: message_start\ndata: {"type":"message_start","message":{"model":"claude-sonnet-4-20250514","usage":{"input_tokens":21,"output_tokens":1}}}\n\n'
            'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Claude response"}}\n\n'
            'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}\n\n'
            'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    adapter = AnthropicAdapter(http_transport=httpx.MockTransport(handler))
    req = GenerationRequest(
        model="claude-sonnet-4-20250514",
        messages=[ChatMessageInput(role="user", content="Hi Claude")],
        system_instruction="System rule",
        temperature=1.8,  # Must clamp to 1.0 per Anthropic spec
        max_output_tokens=512,
    )
    chunks = [c async for c in adapter.stream(req, "sk-ant-test-key-123456")]
    assert "".join(c.delta_text for c in chunks) == "Claude response"
    assert chunks[-1].input_tokens == 21
    assert chunks[-1].output_tokens == 5
    assert captured_body["temperature"] == 1.0
    assert captured_body["system"] == "System rule"


@pytest.mark.asyncio
async def test_retry_exponential_backoff_and_non_retryable_auth_errors():
    calls = 0

    def transient_then_ok(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503, json={"error": {"message": "Upstream overloaded"}}
            )
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [{"message": {"content": "Recovered!"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    adapter = OpenAIAdapter(http_transport=httpx.MockTransport(transient_then_ok))
    res = await adapter.complete(
        GenerationRequest(
            model="gpt-4o-mini",
            messages=[ChatMessageInput(role="user", content="Test")],
        ),
        "sk-valid",
    )
    assert res.content == "Recovered!"
    assert res.retry_count == 1
    assert calls == 2

    # 401 Invalid credentials must NOT retry
    auth_calls = 0

    def unauthorized_handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        auth_calls += 1
        return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})

    bad_adapter = OpenAIAdapter(http_transport=httpx.MockTransport(unauthorized_handler))
    with pytest.raises(ProviderAuthenticationError):
        await bad_adapter.complete(
            GenerationRequest(
                model="gpt-4o-mini",
                messages=[ChatMessageInput(role="user", content="Test")],
            ),
            "sk-invalid",
        )
    assert auth_calls == 1


@pytest.mark.asyncio
async def test_provider_timeout_and_rate_limit_classification():
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out", request=request)

    adapter = OpenAIAdapter(http_transport=httpx.MockTransport(timeout_handler))
    with pytest.raises(ProviderTimeoutError):
        await adapter.complete(
            GenerationRequest(
                model="gpt-4o-mini",
                messages=[ChatMessageInput(role="user", content="Slow")],
            ),
            "sk-key",
        )

    def rate_limit_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "0.05"},
            json={"error": {"message": "Rate limit reached for requests"}},
        )

    rl_adapter = OpenAIAdapter(http_transport=httpx.MockTransport(rate_limit_handler))
    with pytest.raises(ProviderRateLimitError):
        await rl_adapter.complete(
            GenerationRequest(
                model="gpt-4o-mini",
                messages=[ChatMessageInput(role="user", content="Burst")],
            ),
            "sk-key",
        )


def test_encryption_masking_log_redaction_and_registry():
    secret = "sk-testdummykeyvalue987654"
    encrypted = encrypt_api_key(secret)
    assert secret not in encrypted
    assert decrypt_api_key(encrypted) == secret
    assert mask_api_key(secret) == "••••••••••••••••"

    raw_log = f"Header Authorization: Bearer {secret} and token sample"
    scrubbed = redact_secrets(raw_log)
    assert "testdummykeyvalue" not in scrubbed

    record = logging.LogRecord("test", logging.ERROR, __file__, 10, raw_log, (), None)
    assert SecretRedactionFilter().filter(record) is True
    assert "testdummykeyvalue" not in record.msg

    reg = ProviderRegistry()
    reg.register(OpenAIAdapter())
    assert reg.has("openai")
    assert reg.get_model_spec("openai", "gpt-4o") is not None


def test_versioned_pricing_and_context_window_and_attachments():
    # Known model cost estimate
    cost = calculate_estimated_cost(
        provider_key="openai",
        model_id="gpt-4o",
        input_tokens=100_000,
        output_tokens=50_000,
    )
    assert cost.pricing_available is True
    assert cost.is_estimated is True
    assert cost.estimated_cost_usd == Decimal("0.75000000")

    # Unknown custom model must NOT invent fake pricing
    unknown_cost = calculate_estimated_cost(
        provider_key="openai",
        model_id="custom-unpriced-finetune-v9",
        input_tokens=10_000,
        output_tokens=5_000,
    )
    assert unknown_cost.pricing_available is False
    assert unknown_cost.estimated_cost_usd is None

    # Attachment spoofing protection: fake PNG bytes rejected
    with pytest.raises(AppError) as exc_info:
        validate_and_process_attachment(
            filename="fake.png",
            content_type="image/png",
            raw_bytes=b"not a real png header",
            model_supports_vision=True,
        )
    assert exc_info.value.code == "invalid_image_file"

    # Valid PNG accepted
    valid_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    att = validate_and_process_attachment(
        filename="chart.png",
        content_type="image/png",
        raw_bytes=valid_png,
        model_supports_vision=True,
    )
    assert att["kind"] == "image"
    assert base64.b64decode(att["base64_data"]) == valid_png

    # Context window manager trims old messages when budget is tight
    history = [
        Message(role="user", content="A" * 1200, status="completed"),
        Message(role="assistant", content="B" * 1200, status="completed"),
        Message(role="user", content="Recent question", status="completed"),
        Message(role="assistant", content="Recent answer", status="completed"),
    ]
    plan = build_managed_context(
        history_messages=history,
        latest_user_message=ChatMessageInput(role="user", content="Follow-up"),
        system_instruction="Short sys",
        context_window=1024,
        max_output_tokens=200,
        max_ratio=0.8,
    )
    assert plan.omitted_message_count >= 2
    assert plan.messages[-1].content == "Follow-up"
    assert plan.messages[0].role == "user"


@pytest.mark.asyncio
async def test_four_hour_rolling_quota_resets_to_100_percent(app_instance):
    from datetime import datetime, timedelta, timezone
    from app.database import open_session
    from app.models.entities import APIRequest, User
    from app.core.security import hash_password
    from app.services.quota import compute_provider_quota_status

    now = datetime.now(timezone.utc)
    async with open_session() as db:
        u = User(
            email="quota@example.com",
            username="quota_tester",
            password_hash=hash_password("Pass12345!"),
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)

        # Fresh user starts at 100% available across OpenAI, Gemini, and Anthropic
        q0 = await compute_provider_quota_status(db, u.id, "openai", now_override=now)
        assert q0["remaining_pct"] == 100.0

        # Consume 25,000 tokens (25% of 100,000 4h OpenAI window)
        db.add(
            APIRequest(
                request_id="req_quota_test_1",
                user_id=u.id,
                provider_key="openai",
                requested_model="gpt-4o",
                endpoint_type="chat_stream",
                is_streaming=True,
                status="success",
                latency_ms=450.0,
                input_tokens=5000,
                output_tokens=20000,
                total_tokens=25000,
                created_at=now,
            )
        )
        await db.commit()

        q_used = await compute_provider_quota_status(
            db, u.id, "openai", now_override=now + timedelta(minutes=30)
        )
        assert q_used["remaining_pct"] == 75.0

        # After 4 hours + 1 minute, usage automatically recovers back to 100%!
        q_reset = await compute_provider_quota_status(
            db, u.id, "openai", now_override=now + timedelta(hours=4, minutes=1)
        )
        assert q_reset["remaining_pct"] == 100.0
        assert q_reset["used_tokens"] == 0
