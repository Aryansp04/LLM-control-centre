"""Live Provider Integration Tests (`@pytest.mark.live_provider`).

Separated from mocked unit tests per Module 11: executes real upstream LLM API calls
whenever `REAL_OPENAI_API_KEY`, `REAL_GEMINI_API_KEY`, or `REAL_ANTHROPIC_API_KEY`
(or standard `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` with `RUN_LIVE_PROVIDER_TESTS=1`)
are configured in the test environment.
"""

from __future__ import annotations

import os

import pytest

from app.providers.anthropic_adapter import AnthropicAdapter
from app.providers.gemini_adapter import GeminiAdapter
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.types import (
    ChatMessageInput,
    GenerationRequest,
    ProviderRateLimitError,
)

RUN_LIVE = os.getenv("RUN_LIVE_PROVIDER_TESTS", "").lower() in ("1", "true", "yes")


@pytest.mark.live_provider
@pytest.mark.asyncio
@pytest.mark.skipif(
    not (RUN_LIVE and os.getenv("OPENAI_API_KEY")),
    reason="Set RUN_LIVE_PROVIDER_TESTS=1 and OPENAI_API_KEY to run live OpenAI API integration test.",
)
async def test_live_openai_streaming_and_health():
    key = os.environ["OPENAI_API_KEY"]
    adapter = OpenAIAdapter()
    probe = await adapter.probe_provider_and_account(key)
    assert probe.is_healthy is True
    assert probe.account_status == "verified"

    try:
        chunks = [
            c
            async for c in adapter.stream(
                GenerationRequest(
                    model="gpt-4o-mini",
                    messages=[ChatMessageInput(role="user", content="Reply with the single word READY.")],
                    max_output_tokens=16,
                ),
                key,
            )
        ]
    except ProviderRateLimitError as exc:
        if exc.error_type == "quota_exceeded":
            pytest.skip(f"OpenAI key authenticated (/v1/models 200 OK), but billing quota is 0: {exc}")
        raise
    text = "".join(c.delta_text for c in chunks)
    assert len(text.strip()) > 0


@pytest.mark.live_provider
@pytest.mark.asyncio
@pytest.mark.skipif(
    not (RUN_LIVE and os.getenv("GEMINI_API_KEY")),
    reason="Set RUN_LIVE_PROVIDER_TESTS=1 and GEMINI_API_KEY to run live Gemini API integration test.",
)
async def test_live_gemini_streaming_and_health():
    key = os.environ["GEMINI_API_KEY"]
    adapter = GeminiAdapter()
    probe = await adapter.probe_provider_and_account(key)
    assert probe.is_healthy is True
    assert probe.account_status == "verified"

    chunks = [
        c
        async for c in adapter.stream(
            GenerationRequest(
                model="gemini-3.1-flash-lite-preview",
                messages=[ChatMessageInput(role="user", content="Reply with the single word READY.")],
                max_output_tokens=256,
            ),
            key,
        )
    ]
    text = "".join(c.delta_text for c in chunks)
    assert len(text.strip()) > 0


@pytest.mark.live_provider
@pytest.mark.asyncio
@pytest.mark.skipif(
    not (RUN_LIVE and os.getenv("ANTHROPIC_API_KEY")),
    reason="Set RUN_LIVE_PROVIDER_TESTS=1 and ANTHROPIC_API_KEY to run live Anthropic API integration test.",
)
async def test_live_anthropic_streaming_and_health():
    key = os.environ["ANTHROPIC_API_KEY"]
    adapter = AnthropicAdapter()
    probe = await adapter.probe_provider_and_account(key)
    assert probe.is_healthy is True
    assert probe.account_status == "verified"

    try:
        chunks = [
            c
            async for c in adapter.stream(
                GenerationRequest(
                    model="claude-haiku-5-5",
                    messages=[ChatMessageInput(role="user", content="Reply with the single word READY.")],
                    max_output_tokens=16,
                ),
                key,
            )
        ]
    except ProviderRateLimitError as exc:
        if exc.error_type == "quota_exceeded":
            pytest.skip(f"Anthropic key authenticated (/v1/models 200 OK), but billing quota is 0: {exc}")
        raise
    text = "".join(c.delta_text for c in chunks)
    assert len(text.strip()) > 0
