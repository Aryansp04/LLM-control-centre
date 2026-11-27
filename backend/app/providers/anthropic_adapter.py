"""Official Anthropic Claude Messages API REST & SSE Adapter."""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.providers.base import (
    BaseProviderAdapter,
    estimate_tokens_fallback,
    format_message_with_text_attachments,
)
from app.providers.types import (
    GenerationCancelledError,
    GenerationRequest,
    GenerationResult,
    HealthProbeResult,
    ModelSpec,
    ProviderCapabilities,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StreamChunk,
)


class AnthropicAdapter(BaseProviderAdapter):
    provider_key = "anthropic"
    display_name = "Anthropic Claude"
    default_base_url = "https://api.anthropic.com/v1"
    anthropic_version = "2023-06-01"

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_key=self.provider_key,
            display_name=self.display_name,
            supports_streaming=True,
            supports_system_instruction=True,
            supports_temperature=True,
            min_temperature=0.0,
            max_temperature=1.0,  # Anthropic accepts temperature in [0.0, 1.0]
            supports_max_tokens=True,
            supports_vision=True,
            supports_file_attachments=True,
            supports_model_listing=True,
            official_docs_url="https://docs.anthropic.com/en/api/messages",
        )

    def get_default_models(self) -> List[ModelSpec]:
        return [
            ModelSpec(
                provider_key="anthropic",
                model_id="claude-sonnet-5-5",
                display_name="Claude Sonnet 5.5",
                description="High-intelligence Anthropic model balancing speed, coding, and nuanced reasoning.",
                context_window=200000,
                max_output_tokens=64000,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=True,
                supports_max_tokens=True,
                supports_vision=True,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("3.00"),
                output_price_per_1m=Decimal("15.00"),
                pricing_version="2026.11-official-v1",
            ),
            ModelSpec(
                provider_key="anthropic",
                model_id="claude-haiku-5-5",
                display_name="Claude Haiku 5.5",
                description="Fastest Anthropic model engineered for responsive chat and high throughput.",
                context_window=200000,
                max_output_tokens=32000,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=True,
                supports_max_tokens=True,
                supports_vision=True,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("0.80"),
                output_price_per_1m=Decimal("4.00"),
                pricing_version="2026.11-official-v1",
            ),
            ModelSpec(
                provider_key="anthropic",
                model_id="claude-fable-5-2",
                display_name="Claude Fable 5.2",
                description="Long-context 1M-token flagship Anthropic reasoning and code model.",
                context_window=1000000,
                max_output_tokens=128000,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=True,
                supports_max_tokens=True,
                supports_vision=True,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("5.00"),
                output_price_per_1m=Decimal("25.00"),
                pricing_version="2026.11-official-v1",
            ),
        ]

    def _headers(self, api_key: str) -> Dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }

    def _build_payload(self, request: GenerationRequest, stream: bool) -> Dict[str, Any]:
        system_parts: List[str] = []
        if request.system_instruction:
            system_parts.append(request.system_instruction)

        messages_payload: List[Dict[str, Any]] = []
        for msg in request.messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append(msg.content)
                continue

            role = "assistant" if msg.role == "assistant" else "user"
            text_body = format_message_with_text_attachments(msg)
            image_atts = [
                a for a in msg.attachments if a.kind == "image" and a.base64_data and role == "user"
            ]

            if image_atts:
                blocks: List[Dict[str, Any]] = []
                for img in image_atts:
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img.mime_type,
                                "data": img.base64_data,
                            },
                        }
                    )
                if text_body:
                    blocks.append({"type": "text", "text": text_body})
                content_val: Any = blocks
            else:
                content_val = text_body or " "

            # Coalesce consecutive identical roles per Anthropic Messages API rules
            if messages_payload and messages_payload[-1]["role"] == role:
                prev = messages_payload[-1]["content"]
                if isinstance(prev, str) and isinstance(content_val, str):
                    messages_payload[-1]["content"] = f"{prev}\n\n{content_val}"
                else:
                    prev_list = (
                        [{"type": "text", "text": prev}]
                        if isinstance(prev, str)
                        else list(prev)
                    )
                    next_list = (
                        [{"type": "text", "text": content_val}]
                        if isinstance(content_val, str)
                        else list(content_val)
                    )
                    messages_payload[-1]["content"] = prev_list + next_list
            else:
                messages_payload.append({"role": role, "content": content_val})

        spec = self.get_model_spec(request.model)
        default_max = min(4096, spec.max_output_tokens) if spec else 2048
        max_tokens = int(request.max_output_tokens or default_max)

        payload: Dict[str, Any] = {
            "model": request.model,
            "max_tokens": max_tokens,
            "messages": messages_payload,
            "stream": stream,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        if request.temperature is not None:
            # Clamp to Anthropic's [0.0, 1.0] capability range
            payload["temperature"] = max(0.0, min(1.0, float(request.temperature)))

        return payload

    async def complete(
        self,
        request: GenerationRequest,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        organization_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> GenerationResult:
        url = f"{(base_url or self.default_base_url).rstrip('/')}/messages"
        payload = self._build_payload(request, stream=False)
        headers = self._headers(api_key)
        started = time.perf_counter()

        async def _call() -> Dict[str, Any]:
            async with self._build_http_client(request.timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    try:
                        err_body = resp.json()
                    except Exception:
                        err_body = resp.text
                    raise self.classify_http_error(resp.status_code, err_body, resp.headers)
                return resp.json()

        data, retry_count = await self.execute_with_retry(_call, cancel_event=cancel_event)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

        text_parts = [
            str(block.get("text", ""))
            for block in (data.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "".join(text_parts)
        usage = data.get("usage") or {}
        input_tokens = int(
            usage.get("input_tokens") or estimate_tokens_fallback(str(payload))
        )
        output_tokens = int(
            usage.get("output_tokens") or estimate_tokens_fallback(content)
        )
        tps = (
            round(output_tokens / (latency_ms / 1000.0), 2)
            if latency_ms > 0 and output_tokens > 0
            else None
        )
        return GenerationResult(
            content=content,
            actual_model=str(data.get("model") or request.model),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            ttft_ms=latency_ms,
            tokens_per_second=tps,
            retry_count=retry_count,
            finish_reason=str(data.get("stop_reason") or "end_turn"),
        )

    async def stream(
        self,
        request: GenerationRequest,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        organization_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[StreamChunk]:
        url = f"{(base_url or self.default_base_url).rstrip('/')}/messages"
        payload = self._build_payload(request, stream=True)
        headers = self._headers(api_key)

        attempt = 0
        max_retries = 2

        while True:
            if cancel_event and cancel_event.is_set():
                raise GenerationCancelledError("Generation cancelled")
            try:
                async with self._build_http_client(request.timeout_seconds) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as resp:
                        if resp.status_code >= 400:
                            raw_err = await resp.aread()
                            try:
                                err_body = json.loads(raw_err.decode("utf-8", errors="replace"))
                            except Exception:
                                err_body = raw_err.decode("utf-8", errors="replace")
                            raise self.classify_http_error(
                                resp.status_code, err_body, resp.headers
                            )

                        actual_model: Optional[str] = None
                        input_tokens: Optional[int] = None
                        output_tokens: Optional[int] = None
                        finish_reason: Optional[str] = None

                        async for line in resp.aiter_lines():
                            if cancel_event and cancel_event.is_set():
                                raise GenerationCancelledError("Generation cancelled by user")

                            line = line.strip()
                            if not line or not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if not data_str:
                                continue

                            ev = json.loads(data_str)
                            ev_type = ev.get("type")

                            if ev_type == "message_start":
                                msg_obj = ev.get("message") or {}
                                if msg_obj.get("model"):
                                    actual_model = str(msg_obj["model"])
                                usage = msg_obj.get("usage") or {}
                                if usage.get("input_tokens") is not None:
                                    input_tokens = int(usage["input_tokens"])
                                if usage.get("output_tokens") is not None:
                                    output_tokens = int(usage["output_tokens"])

                            elif ev_type == "content_block_delta":
                                delta = ev.get("delta") or {}
                                if delta.get("type") == "text_delta" and delta.get("text"):
                                    yield StreamChunk(
                                        delta_text=str(delta["text"]),
                                        actual_model=actual_model or request.model,
                                    )

                            elif ev_type == "message_delta":
                                delta = ev.get("delta") or {}
                                if delta.get("stop_reason"):
                                    finish_reason = str(delta["stop_reason"])
                                usage = ev.get("usage") or {}
                                if usage.get("output_tokens") is not None:
                                    output_tokens = int(usage["output_tokens"])

                            elif ev_type == "error":
                                err_info = ev.get("error") or {}
                                raise self.classify_http_error(
                                    529 if err_info.get("type") == "overloaded_error" else 500,
                                    {"error": err_info},
                                    resp.headers,
                                )

                            elif ev_type == "message_stop":
                                yield StreamChunk(
                                    delta_text="",
                                    actual_model=actual_model or request.model,
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                    finish_reason=finish_reason or "end_turn",
                                    is_final=True,
                                )
                                return

                        yield StreamChunk(
                            delta_text="",
                            actual_model=actual_model or request.model,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            finish_reason=finish_reason or "end_turn",
                            is_final=True,
                        )
                        return

            except GenerationCancelledError:
                raise
            except ProviderError as exc:
                if not exc.retryable or attempt >= max_retries:
                    raise
                attempt += 1
                await self._sleep_with_cancel(0.6 * (2**attempt), cancel_event)
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                if attempt >= max_retries:
                    raise ProviderTimeoutError(
                        f"Anthropic streaming timed out ({type(exc).__name__})",
                        provider_key=self.provider_key,
                    ) from exc
                attempt += 1
                await self._sleep_with_cancel(0.6 * (2**attempt), cancel_event)
            except httpx.RequestError as exc:
                if attempt >= max_retries:
                    raise ProviderUnavailableError(
                        f"Network error contacting Anthropic ({type(exc).__name__})",
                        provider_key=self.provider_key,
                    ) from exc
                attempt += 1
                await self._sleep_with_cancel(0.6 * (2**attempt), cancel_event)

    async def probe_provider_and_account(
        self,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> HealthProbeResult:
        url = f"{(base_url or self.default_base_url).rstrip('/')}/models"
        headers = self._headers(api_key)
        started = time.perf_counter()
        try:
            async with self._build_http_client(15.0) as client:
                resp = await client.get(url, headers=headers)
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            if resp.status_code >= 400:
                try:
                    err_body = resp.json()
                except Exception:
                    err_body = resp.text
                err = self.classify_http_error(resp.status_code, err_body, resp.headers)
                return self._from_error(err, latency_ms, "provider_auth")

            body = resp.json()
            discovered = [
                str(m.get("id"))
                for m in (body.get("data") or [])
                if isinstance(m, dict) and m.get("id")
            ]
            return HealthProbeResult(
                provider_key=self.provider_key,
                check_scope="provider_auth",
                provider_status="degraded" if latency_ms > 3500 else "operational",
                account_status="verified",
                is_healthy=True,
                latency_ms=latency_ms,
                http_status_code=resp.status_code,
                discovered_model_ids=discovered,
                details={"models_returned": len(discovered)},
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return HealthProbeResult(
                provider_key=self.provider_key,
                check_scope="provider_auth",
                provider_status="unavailable",
                account_status="configured",
                is_healthy=False,
                latency_ms=latency_ms,
                error_message=f"Anthropic API unreachable ({type(exc).__name__})",
            )

    async def probe_model(
        self,
        api_key: str,
        model_id: str,
        *,
        deep_inference: bool = False,
        base_url: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> HealthProbeResult:
        root = (base_url or self.default_base_url).rstrip("/")
        headers = self._headers(api_key)
        started = time.perf_counter()

        try:
            async with self._build_http_client(20.0) as client:
                if deep_inference:
                    resp = await client.post(
                        f"{root}/messages",
                        headers=headers,
                        json={
                            "model": model_id,
                            "max_tokens": 1,
                            "messages": [{"role": "user", "content": "ping"}],
                        },
                    )
                    scope = "model_inference"
                else:
                    resp = await client.get(f"{root}/models/{model_id}", headers=headers)
                    scope = "model_availability"

            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            if resp.status_code >= 400:
                try:
                    err_body = resp.json()
                except Exception:
                    err_body = resp.text
                err = self.classify_http_error(resp.status_code, err_body, resp.headers)
                res = self._from_error(err, latency_ms, scope)
                res.model_id = model_id
                return res

            return HealthProbeResult(
                provider_key=self.provider_key,
                check_scope=scope,
                provider_status="degraded" if latency_ms > 4000 else "operational",
                account_status="verified",
                model_status="request_successful" if deep_inference else "reachable",
                model_id=model_id,
                is_healthy=True,
                latency_ms=latency_ms,
                http_status_code=resp.status_code,
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return HealthProbeResult(
                provider_key=self.provider_key,
                check_scope="model_inference" if deep_inference else "model_availability",
                provider_status="unavailable",
                account_status="configured",
                model_status="request_failed",
                model_id=model_id,
                is_healthy=False,
                latency_ms=latency_ms,
                error_message=f"Anthropic model probe failed ({type(exc).__name__})",
            )

    def _from_error(
        self, err: ProviderError, latency_ms: float, scope: str
    ) -> HealthProbeResult:
        if err.error_type == "invalid_credentials":
            return HealthProbeResult(
                provider_key=self.provider_key,
                check_scope=scope,
                provider_status="operational",
                account_status="invalid_credentials",
                model_status="request_failed",
                is_healthy=False,
                latency_ms=latency_ms,
                http_status_code=err.status_code,
                error_message=str(err),
            )
        if err.error_type in ("rate_limited", "quota_exceeded"):
            return HealthProbeResult(
                provider_key=self.provider_key,
                check_scope=scope,
                provider_status="degraded",
                account_status=err.error_type,
                model_status="rate_limited",
                is_healthy=False,
                latency_ms=latency_ms,
                http_status_code=err.status_code,
                error_message=str(err),
            )
        if err.error_type in ("provider_unavailable", "timeout"):
            return HealthProbeResult(
                provider_key=self.provider_key,
                check_scope=scope,
                provider_status="unavailable",
                account_status="configured",
                model_status="request_failed",
                is_healthy=False,
                latency_ms=latency_ms,
                http_status_code=err.status_code,
                error_message=str(err),
            )
        return HealthProbeResult(
            provider_key=self.provider_key,
            check_scope=scope,
            provider_status="operational",
            account_status="verified",
            model_status="request_failed",
            is_healthy=False,
            latency_ms=latency_ms,
            http_status_code=err.status_code,
            error_message=str(err),
        )
