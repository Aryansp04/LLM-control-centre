"""Official OpenAI REST & SSE Streaming Adapter."""

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


class OpenAIAdapter(BaseProviderAdapter):
    provider_key = "openai"
    display_name = "OpenAI"
    default_base_url = "https://api.openai.com/v1"

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_key=self.provider_key,
            display_name=self.display_name,
            supports_streaming=True,
            supports_system_instruction=True,
            supports_temperature=True,
            min_temperature=0.0,
            max_temperature=2.0,
            supports_max_tokens=True,
            supports_vision=True,
            supports_file_attachments=True,
            supports_model_listing=True,
            official_docs_url="https://platform.openai.com/docs/api-reference",
        )

    def get_default_models(self) -> List[ModelSpec]:
        return [
            ModelSpec(
                provider_key="openai",
                model_id="gpt-4o",
                display_name="GPT-4o",
                description="Flagship multimodal model for complex reasoning, code, and vision.",
                context_window=128000,
                max_output_tokens=16384,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=True,
                supports_max_tokens=True,
                supports_vision=True,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("2.50"),
                output_price_per_1m=Decimal("10.00"),
                pricing_version="2026.11-official-v1",
            ),
            ModelSpec(
                provider_key="openai",
                model_id="gpt-4o-mini",
                display_name="GPT-4o mini",
                description="Fast, low-latency multimodal model ideal for high-throughput workloads.",
                context_window=128000,
                max_output_tokens=16384,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=True,
                supports_max_tokens=True,
                supports_vision=True,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("0.15"),
                output_price_per_1m=Decimal("0.60"),
                pricing_version="2026.11-official-v1",
            ),
            ModelSpec(
                provider_key="openai",
                model_id="gpt-5-mini",
                display_name="GPT-5 mini",
                description="Next-generation compact OpenAI reasoning and coding model.",
                context_window=200000,
                max_output_tokens=65536,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=False,
                supports_max_tokens=True,
                supports_vision=True,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("0.25"),
                output_price_per_1m=Decimal("2.00"),
                pricing_version="2026.11-official-v1",
            ),
            ModelSpec(
                provider_key="openai",
                model_id="o3-mini",
                display_name="o3-mini (Reasoning)",
                description="STEM and coding reasoning model (fixed temperature, developer instructions).",
                context_window=200000,
                max_output_tokens=100000,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=False,  # Reasoning model does not accept temperature!
                supports_max_tokens=True,
                supports_vision=False,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("1.10"),
                output_price_per_1m=Decimal("4.40"),
                pricing_version="2026.11-official-v1",
            ),
        ]

    @staticmethod
    def _is_reasoning_model(model_id: str) -> bool:
        m = model_id.lower()
        return m.startswith(("o1", "o3", "o4", "gpt-5"))

    def _headers(self, api_key: str, organization_id: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if organization_id:
            headers["OpenAI-Organization"] = organization_id
        return headers

    def _build_payload(self, request: GenerationRequest, stream: bool) -> Dict[str, Any]:
        is_reasoning = self._is_reasoning_model(request.model)
        spec = self.get_model_spec(request.model)
        supports_vision = spec.supports_vision if spec else (not is_reasoning)
        supports_temp = (spec.supports_temperature if spec else True) and not is_reasoning

        messages_payload: List[Dict[str, Any]] = []
        if request.system_instruction:
            sys_role = "developer" if is_reasoning else "system"
            messages_payload.append({"role": sys_role, "content": request.system_instruction})

        for msg in request.messages:
            text_body = format_message_with_text_attachments(msg)
            image_atts = [
                a for a in msg.attachments if a.kind == "image" and a.base64_data and supports_vision
            ]
            if image_atts and msg.role == "user":
                content_blocks: List[Dict[str, Any]] = []
                if text_body:
                    content_blocks.append({"type": "text", "text": text_body})
                for img in image_atts:
                    content_blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{img.mime_type};base64,{img.base64_data}"
                            },
                        }
                    )
                messages_payload.append({"role": msg.role, "content": content_blocks})
            else:
                role = (
                    "developer"
                    if (msg.role == "system" and is_reasoning)
                    else msg.role
                )
                messages_payload.append({"role": role, "content": text_body})

        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": messages_payload,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}

        if supports_temp and request.temperature is not None:
            payload["temperature"] = max(0.0, min(2.0, float(request.temperature)))

        if request.max_output_tokens is not None:
            if is_reasoning:
                payload["max_completion_tokens"] = int(request.max_output_tokens)
            else:
                payload["max_tokens"] = int(request.max_output_tokens)

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
        url = f"{(base_url or self.default_base_url).rstrip('/')}/chat/completions"
        payload = self._build_payload(request, stream=False)
        headers = self._headers(api_key, organization_id)

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

        choices = data.get("choices") or []
        content = ""
        finish_reason = "stop"
        if choices:
            content = choices[0].get("message", {}).get("content") or ""
            finish_reason = choices[0].get("finish_reason") or "stop"

        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or estimate_tokens_fallback(str(payload)))
        output_tokens = int(usage.get("completion_tokens") or estimate_tokens_fallback(content))
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
            finish_reason=finish_reason,
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
        url = f"{(base_url or self.default_base_url).rstrip('/')}/chat/completions"
        payload = self._build_payload(request, stream=True)
        headers = self._headers(api_key, organization_id)

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
                            if data_str == "[DONE]":
                                yield StreamChunk(
                                    delta_text="",
                                    actual_model=actual_model or request.model,
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                    finish_reason=finish_reason or "stop",
                                    is_final=True,
                                )
                                return

                            event_json = json.loads(data_str)
                            if event_json.get("model"):
                                actual_model = str(event_json["model"])

                            usage = event_json.get("usage")
                            if isinstance(usage, dict):
                                if usage.get("prompt_tokens") is not None:
                                    input_tokens = int(usage["prompt_tokens"])
                                if usage.get("completion_tokens") is not None:
                                    output_tokens = int(usage["completion_tokens"])

                            choices = event_json.get("choices") or []
                            if choices:
                                choice = choices[0]
                                if choice.get("finish_reason"):
                                    finish_reason = str(choice["finish_reason"])
                                delta = choice.get("delta") or {}
                                text_piece = delta.get("content") or ""
                                if text_piece:
                                    yield StreamChunk(
                                        delta_text=text_piece,
                                        actual_model=actual_model,
                                    )
                        # Stream closed without [DONE]
                        yield StreamChunk(
                            delta_text="",
                            actual_model=actual_model or request.model,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            finish_reason=finish_reason or "stop",
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
                        f"OpenAI streaming timed out ({type(exc).__name__})",
                        provider_key=self.provider_key,
                    ) from exc
                attempt += 1
                await self._sleep_with_cancel(0.6 * (2**attempt), cancel_event)
            except httpx.RequestError as exc:
                if attempt >= max_retries:
                    raise ProviderUnavailableError(
                        f"Network error contacting OpenAI ({type(exc).__name__})",
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
        headers = self._headers(api_key, organization_id)
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
                return self._probe_result_from_error(err, latency_ms, "provider_auth")

            body = resp.json()
            discovered = [
                str(item.get("id"))
                for item in (body.get("data") or [])
                if isinstance(item, dict) and item.get("id")
            ]
            provider_status = "degraded" if latency_ms > 3500 else "operational"
            return HealthProbeResult(
                provider_key=self.provider_key,
                check_scope="provider_auth",
                provider_status=provider_status,
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
                error_message=f"OpenAI API unreachable ({type(exc).__name__})",
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
        headers = self._headers(api_key, organization_id)
        started = time.perf_counter()

        try:
            async with self._build_http_client(20.0) as client:
                if deep_inference:
                    is_reasoning = self._is_reasoning_model(model_id)
                    body: Dict[str, Any] = {
                        "model": model_id,
                        "messages": [{"role": "user", "content": "ping"}],
                    }
                    if is_reasoning:
                        body["max_completion_tokens"] = 8
                    else:
                        body["max_tokens"] = 1
                        body["temperature"] = 0
                    resp = await client.post(
                        f"{root}/chat/completions", headers=headers, json=body
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
                res = self._probe_result_from_error(err, latency_ms, scope)
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
                error_message=f"Model check failed ({type(exc).__name__})",
            )

    def _probe_result_from_error(
        self, err: ProviderError, latency_ms: float, scope: str
    ) -> HealthProbeResult:
        if err.error_type == "invalid_credentials":
            return HealthProbeResult(
                provider_key=self.provider_key,
                check_scope=scope,
                provider_status="operational",  # API endpoint itself responded!
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
