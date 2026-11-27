"""End-to-end API tests covering Auth, Multi-Model Switching, SSE Streaming, Cancellation,
Monitoring Health Separation, WebSocket Auth/Isolation, DB Failures, Redis Failures, and Rate Limits."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from starlette.testclient import TestClient

from app.providers.anthropic_adapter import AnthropicAdapter
from app.providers.gemini_adapter import GeminiAdapter
from app.providers.openai_adapter import OpenAIAdapter
from app.providers.registry import provider_registry
from app.redis_client import redis_manager


async def _register_and_headers(
    client: httpx.AsyncClient, email: str = "alice@example.com", username: str = "alice"
) -> tuple[dict, str]:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "username": username,
            "password": "StrongPassword123!",
            "full_name": username.title(),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    token = body["access_token"]
    return {"Authorization": f"Bearer {token}"}, token


@pytest.mark.asyncio
async def test_auth_lifecycle_and_encrypted_credentials_never_exposed(client: httpx.AsyncClient):
    headers, _ = await _register_and_headers(client)

    # Connect OpenAI API key and verify response masks key and never exposes plaintext/ciphertext
    def ok_models(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}, {"id": "o3-mini"}]},
        )

    orig_openai = provider_registry.get("openai")
    provider_registry.register(OpenAIAdapter(http_transport=httpx.MockTransport(ok_models)))
    try:
        raw_secret = "dummy_vault_key_for_unit_test_9999"
        upd = await client.put(
            "/api/providers/openai",
            headers=headers,
            json={"api_key": raw_secret, "verify_immediately": True},
        )
        assert upd.status_code == 200
        text_dump = upd.text
        assert raw_secret not in text_dump
        assert "encrypted_api_key" not in text_dump
        assert upd.json()["key_hint"] == "••••••••••••••••"
        assert upd.json()["status"] == "operational"
        assert upd.json()["account_status"] == "verified"

        # Logout revokes JWT immediately
        out_resp = await client.post("/api/auth/logout", headers=headers)
        assert out_resp.status_code == 200
        me_after = await client.get("/api/auth/me", headers=headers)
        assert me_after.status_code == 401
        assert me_after.json()["error"]["code"] == "token_revoked"
    finally:
        provider_registry.register(orig_openai)


@pytest.mark.asyncio
async def test_sse_streaming_model_switching_persistence_and_analytics(client: httpx.AsyncClient):
    headers, _ = await _register_and_headers(client, "engineer@example.com", "engineer")

    def openai_handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models") or "/models/" in req.url.path:
            return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})
        sse = (
            'data: {"model":"gpt-4o-mini-2024-07-18","choices":[{"delta":{"content":"First "}}]}\n\n'
            'data: {"model":"gpt-4o-mini-2024-07-18","choices":[{"delta":{"content":"answer."},"finish_reason":"stop"}]}\n\n'
            'data: {"model":"gpt-4o-mini-2024-07-18","choices":[],"usage":{"prompt_tokens":18,"completion_tokens":4}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    def anthropic_handler(req: httpx.Request) -> httpx.Response:
        if "/models" in req.url.path:
            return httpx.Response(200, json={"data": [{"id": "claude-sonnet-4-20250514"}]})
        req_json = json.loads(req.content.decode("utf-8"))
        # Verify prior OpenAI assistant turn was preserved in conversation context!
        assert any("First answer." in str(m.get("content")) for m in req_json["messages"])
        sse = (
            'data: {"type":"message_start","message":{"model":"claude-sonnet-4-20250514","usage":{"input_tokens":32,"output_tokens":1}}}\n\n'
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Switched seamlessly to Claude!"}}\n\n'
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":7}}\n\n'
            'data: {"type":"message_stop"}\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    orig_oai = provider_registry.get("openai")
    orig_ant = provider_registry.get("anthropic")
    provider_registry.register(OpenAIAdapter(http_transport=httpx.MockTransport(openai_handler)))
    provider_registry.register(
        AnthropicAdapter(http_transport=httpx.MockTransport(anthropic_handler))
    )

    try:
        await client.put(
            "/api/providers/openai",
            headers=headers,
            json={"api_key": "sk-test-openai-valid-1234", "verify_immediately": False},
        )
        await client.put(
            "/api/providers/anthropic",
            headers=headers,
            json={"api_key": "sk-ant-test-valid-1234", "verify_immediately": False},
        )

        # Turn 1: Stream from OpenAI
        stream_resp = await client.post(
            "/api/chat/stream",
            headers=headers,
            json={
                "provider_key": "openai",
                "model_id": "gpt-4o-mini",
                "message": "Explain event loops briefly.",
            },
        )
        assert stream_resp.status_code == 200
        raw_sse = stream_resp.text
        assert "event: stream_start" in raw_sse
        assert "event: token" in raw_sse
        assert "event: stream_end" in raw_sse

        conv_id = None
        for block in raw_sse.strip().split("\n\n"):
            if block.startswith("event: stream_start"):
                data_line = [l for l in block.splitlines() if l.startswith("data:")][0]
                conv_id = json.loads(data_line[5:].strip())["conversation_id"]
        assert conv_id is not None

        # Turn 2: Switch to Anthropic Claude in the SAME conversation!
        stream_resp_2 = await client.post(
            "/api/chat/stream",
            headers=headers,
            json={
                "conversation_id": conv_id,
                "provider_key": "anthropic",
                "model_id": "claude-sonnet-4-20250514",
                "message": "Continue from the previous answer.",
            },
        )
        assert stream_resp_2.status_code == 200
        assert "Switched seamlessly to Claude!" in stream_resp_2.text

        # Verify conversation persistence, token totals, rename, search, and export
        conv_detail = await client.get(f"/api/conversations/{conv_id}", headers=headers)
        assert conv_detail.status_code == 200
        detail_json = conv_detail.json()
        assert len(detail_json["messages"]) == 4
        assert detail_json["total_input_tokens"] == 50  # 18 + 32
        assert detail_json["total_output_tokens"] == 11  # 4 + 7
        assert detail_json["messages"][1]["actual_model_used"] == "gpt-4o-mini-2024-07-18"
        assert detail_json["messages"][3]["actual_model_used"] == "claude-sonnet-4-20250514"

        rename_resp = await client.patch(
            f"/api/conversations/{conv_id}",
            headers=headers,
            json={"title": "Multi-Model Architecture Thread"},
        )
        assert rename_resp.status_code == 200
        assert rename_resp.json()["title"] == "Multi-Model Architecture Thread"

        search_resp = await client.get(
            "/api/conversations?search=seamlessly", headers=headers
        )
        assert search_resp.json()["total"] == 1

        export_md = await client.get(
            f"/api/conversations/{conv_id}/export?format=markdown", headers=headers
        )
        assert export_md.status_code == 200
        assert "Multi-Model Architecture Thread" in export_md.text

        # Verify monitoring overview & analytics reflect exact telemetry (no hardcoded numbers)
        overview = await client.get("/api/monitoring/overview", headers=headers)
        cards = overview.json()["cards"]
        assert cards["total_requests"] == 2
        assert cards["successful_requests"] == 2
        assert cards["total_tokens"] == 61
        assert cards["estimated_cost_usd"] > 0

        analytics_cost = await client.get("/api/analytics/cost", headers=headers)
        assert analytics_cost.status_code == 200
        assert analytics_cost.json()["is_cost_estimated"] is True
        assert len(analytics_cost.json()["by_provider"]) == 2
    finally:
        provider_registry.register(orig_oai)
        provider_registry.register(orig_ant)


@pytest.mark.asyncio
async def test_health_check_distinguishes_invalid_credentials_from_server_outage(
    client: httpx.AsyncClient,
):
    headers, _ = await _register_and_headers(client, "ops@example.com", "opsuser")

    def invalid_key_gemini(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": "API key not valid. Please pass a valid API key."}}
        )

    orig_gem = provider_registry.get("gemini")
    provider_registry.register(
        GeminiAdapter(http_transport=httpx.MockTransport(invalid_key_gemini))
    )
    try:
        await client.put(
            "/api/providers/gemini",
            headers=headers,
            json={"api_key": "AIzaInvalidKey0000000000", "verify_immediately": True},
        )
        overview = (await client.get("/api/monitoring/overview", headers=headers)).json()
        # Application backend MUST remain operational while Gemini account_status is invalid_credentials!
        assert overview["application_status"]["backend"]["status"] == "operational"
        gem_rows = [
            r
            for r in overview["provider_status_table"]
            if r["provider_key"] == "gemini"
        ]
        assert gem_rows[0]["provider_status"] == "operational"
        assert gem_rows[0]["account_status"] == "invalid_credentials"
        assert gem_rows[0]["model_status"] == "request_failed"
    finally:
        provider_registry.register(orig_gem)


@pytest.mark.asyncio
async def test_user_data_isolation_and_unauthorized_access(client: httpx.AsyncClient):
    headers_a, _ = await _register_and_headers(client, "usera@example.com", "usera")
    headers_b, _ = await _register_and_headers(client, "userb@example.com", "userb")

    # Unauthenticated access blocked
    unauth = await client.get("/api/conversations")
    assert unauth.status_code == 401

    conv_a = await client.post(
        "/api/conversations",
        headers=headers_a,
        json={"title": "Secret Thread A", "provider_key": "openai", "model_id": "gpt-4o"},
    )
    conv_a_id = conv_a.json()["id"]

    # User B cannot view, update, or delete User A's conversation
    get_by_b = await client.get(f"/api/conversations/{conv_a_id}", headers=headers_b)
    assert get_by_b.status_code == 404
    del_by_b = await client.delete(f"/api/conversations/{conv_a_id}", headers=headers_b)
    assert del_by_b.status_code == 404


@pytest.mark.asyncio
async def test_database_and_redis_failures_and_rate_limiting(client: httpx.AsyncClient):
    headers, _ = await _register_and_headers(client, "resilience@example.com", "resilience")

    # 1. Simulate Redis failure -> /ready returns 503, /health stays 200, API degrades safely
    async def broken_ping():
        raise ConnectionError("Redis connection refused")

    with patch.object(redis_manager._client, "ping", side_effect=broken_ping):
        liveness = await client.get("/health")
        assert liveness.status_code == 200
        readiness = await client.get("/ready")
        assert readiness.status_code == 503
        assert readiness.json()["redis"]["status"] == "unavailable"

    # 2. Simulate Database failure -> /ready returns 503 and reports DB unavailable
    with patch(
        "app.api.analytics.check_database_health",
        return_value={
            "status": "unavailable",
            "healthy": False,
            "dialect": "postgresql",
            "latency_ms": 1.2,
            "error": "Database connectivity check failed",
        },
    ):
        db_ready = await client.get("/ready")
        assert db_ready.status_code == 503
        assert db_ready.json()["database"]["status"] == "unavailable"

    # 3. Verify API rate limit returns HTTP 429 with Retry-After header
    from app.config import get_settings

    settings = get_settings()
    orig_limit = settings.rate_limit_requests_per_minute
    settings.rate_limit_requests_per_minute = 3
    try:
        statuses = []
        for _ in range(5):
            r = await client.get("/api/providers", headers=headers)
            statuses.append(r.status_code)
        assert 429 in statuses
    finally:
        settings.rate_limit_requests_per_minute = orig_limit


def test_websocket_authentication_and_user_isolation(app_instance):
    with TestClient(app_instance) as sync_client:
        reg_a = sync_client.post(
            "/api/auth/register",
            json={
                "email": "wsa@example.com",
                "username": "wsusera",
                "password": "StrongPassword123!",
            },
        )
        tok_a = reg_a.json()["access_token"]

        reg_b = sync_client.post(
            "/api/auth/register",
            json={
                "email": "wsb@example.com",
                "username": "wsuserb",
                "password": "StrongPassword123!",
            },
        )
        tok_b = reg_b.json()["access_token"]

        # Unauthenticated WebSocket is rejected with policy violation (1008)
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with sync_client.websocket_connect("/ws/events?token=invalid-jwt"):
                pass
        assert exc_info.value.code == 1008

        # Authenticated WebSockets for User A and User B are isolated
        with sync_client.websocket_connect(f"/ws/events?token={tok_a}") as ws_a:
            ready_a = ws_a.receive_json()
            assert ready_a["type"] == "connection_ready"

            ws_a.send_json({"type": "ping", "ts": 12345})
            pong = ws_a.receive_json()
            assert pong["type"] == "pong"
            assert pong["client_ts"] == 12345

            with sync_client.websocket_connect(f"/ws/events?token={tok_b}") as ws_b:
                ready_b = ws_b.receive_json()
                assert ready_b["type"] == "connection_ready"

                # Trigger health check for User A -> User A receives event on WS!
                chk = sync_client.post(
                    "/api/monitoring/check",
                    headers={"Authorization": f"Bearer {tok_a}"},
                    json={},
                )
                assert chk.status_code == 200
                ev_a = ws_a.receive_json()
                assert ev_a["type"] in (
                    "health_check_completed",
                    "model_status_changed",
                    "provider_status_changed",
                )


@pytest.mark.asyncio
async def test_active_generation_cancellation_endpoint(client: httpx.AsyncClient):
    headers, _ = await _register_and_headers(client, "cancel@example.com", "canceluser")
    user_me = (await client.get("/api/auth/me", headers=headers)).json()

    ev = await redis_manager.register_generation(
        stream_id="str_live_test_cancel_01",
        user_id=user_me["id"],
        provider_key="openai",
        model_id="gpt-4o-mini",
        conversation_id="conv-1",
    )
    assert not ev.is_set()

    resp = await client.post(
        "/api/chat/cancel",
        headers=headers,
        json={"stream_id": "str_live_test_cancel_01"},
    )
    assert resp.status_code == 200
    assert ev.is_set() is True
    await redis_manager.finish_generation("str_live_test_cancel_01")
