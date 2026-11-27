"""Official Google Gemini Generative Language API REST & SSE Adapter."""

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


class GeminiAdapter(BaseProviderAdapter):
    provider_key = "gemini"
    display_name = "Google Gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

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
            official_docs_url="https://ai.google.dev/gemini-api/docs",
        )

    def get_default_models(self) -> List[ModelSpec]:
        return [
            ModelSpec(
                provider_key="gemini",
                model_id="gemini-3-flash-preview",
                display_name="Gemini 3 Flash",
                description="Fast, high-intelligence multimodal model verified for low-latency streaming.",
                context_window=1048576,
                max_output_tokens=65536,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=True,
                supports_max_tokens=True,
                supports_vision=True,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("0.30"),
                output_price_per_1m=Decimal("2.50"),
                pricing_version="2026.11-official-v1",
            ),
            ModelSpec(
                provider_key="gemini",
                model_id="gemini-3.1-flash-lite-preview",
                display_name="Gemini 3.1 Flash Lite",
                description="Ultra-fast, cost-efficient multimodal model for high-throughput chat.",
                context_window=1048576,
                max_output_tokens=65536,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=True,
                supports_max_tokens=True,
                supports_vision=True,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("0.10"),
                output_price_per_1m=Decimal("0.40"),
                pricing_version="2026.11-official-v1",
            ),
            ModelSpec(
                provider_key="gemini",
                model_id="gemini-3.8-flash",
                display_name="Gemini 3.8 Flash",
                description="Latest generation Gemini Flash model with 1M context window.",
                context_window=1048576,
                max_output_tokens=65536,
                supports_streaming=True,
                supports_system_instruction=True,
                supports_temperature=True,
                supports_max_tokens=True,
                supports_vision=True,
                supports_file_attachments=True,
                input_price_per_1m=Decimal("0.35"),
                output_price_per_1m=Decimal("2.80"),
                pricing_version="2026.11-official-v1",
            ),
        ]

    @staticmethod
    def _headers(api_key: str) -> Dict[str, str]:
        # Key passed in header so URLs never contain sensitive credentials.
        return {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: GenerationRequest) -> Dict[str, Any]:
        contents: List[Dict[str, Any]] = []
        system_parts: List[str] = []
        if request.system_instruction:
            system_parts.append(request.system_instruction)

        for msg in request.messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append(msg.content)
                continue

            gemini_role = "model" if msg.role == "assistant" else "user"
            parts: List[Dict[str, Any]] = []
            text_body = format_message_with_text_attachments(msg)
            if text_body:
                parts.append({"text": text_body})

            for att in msg.attachments:
                if att.kind in ("image", "pdf") and att.base64_data and gemini_role == "user":
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": att.mime_type,
                                "data": att.base64_data,
                            }
                        }
                    )
            if not parts:
                parts.append({"text": " "})
            contents.append({"role": gemini_role, "parts": parts})

        payload: Dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }

        gen_config: Dict[str, Any] = {}
        if request.temperature is not None:
            gen_config["temperature"] = max(0.0, min(2.0, float(request.temperature)))
        if request.max_output_tokens is not None:
            gen_config["maxOutputTokens"] = int(request.max_output_tokens)
        if gen_config:
            payload["generationConfig"] = gen_config

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
        model_path = request.model.removeprefix("models/")
        url = f"{(base_url or self.default_base_url).rstrip('/')}/models/{model_path}:generateContent"
        payload = self._build_payload(request)
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

        text_chunks: List[str] = []
        finish_reason = "STOP"
        for cand in data.get("candidates") or []:
            if cand.get("finishReason"):
                finish_reason = str(cand["finishReason"])
            for part in (cand.get("content") or {}).get("parts") or []:
                if part.get("thought") is True:
                    continue
                if part.get("text"):
                    text_chunks.append(str(part["text"]))

        content = "".join(text_chunks)
        usage = data.get("usageMetadata") or {}
        input_tokens = int(
            usage.get("promptTokenCount") or estimate_tokens_fallback(str(payload))
        )
        output_tokens = int(
            usage.get("candidatesTokenCount") or estimate_tokens_fallback(content)
        )
        tps = (
            round(output_tokens / (latency_ms / 1000.0), 2)
            if latency_ms > 0 and output_tokens > 0
            else None
        )
        actual_model = str(data.get("modelVersion") or model_path)
        return GenerationResult(
            content=content,
            actual_model=actual_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            ttft_ms=latency_ms,
            tokens_per_second=tps,
            retry_count=retry_count,
            finish_reason=finish_reason.lower(),
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
        model_path = request.model.removeprefix("models/")
        url = (
            f"{(base_url or self.default_base_url).rstrip('/')}"
            f"/models/{model_path}:streamGenerateContent?alt=sse"
        )
        payload = self._build_payload(request)
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
                            if not data_str or data_str == "[DONE]":
                                continue

                            chunk_json = json.loads(data_str)
                            if chunk_json.get("modelVersion"):
                                actual_model = str(chunk_json["modelVersion"])

                            usage = chunk_json.get("usageMetadata")
                            if isinstance(usage, dict):
                                if usage.get("promptTokenCount") is not None:
                                    input_tokens = int(usage["promptTokenCount"])
                                if usage.get("candidatesTokenCount") is not None:
                                    output_tokens = int(usage["candidatesTokenCount"])

                            for cand in chunk_json.get("candidates") or []:
                                if cand.get("finishReason"):
                                    finish_reason = str(cand["finishReason"]).lower()
                                for part in (cand.get("content") or {}).get("parts") or []:
                                    if part.get("thought") is True:
                                        continue
                                    txt = part.get("text")
                                    if txt:
                                        yield StreamChunk(
                                            delta_text=str(txt),
                                            actual_model=actual_model or model_path,
                                        )

                        yield StreamChunk(
                            delta_text="",
                            actual_model=actual_model or model_path,
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
                        f"Gemini streaming timed out ({type(exc).__name__})",
                        provider_key=self.provider_key,
                    ) from exc
                attempt += 1
                await self._sleep_with_cancel(0.6 * (2**attempt), cancel_event)
            except httpx.RequestError as exc:
                if attempt >= max_retries:
                    raise ProviderUnavailableError(
                        f"Network error contacting Gemini ({type(exc).__name__})",
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
        url = f"{(base_url or self.default_base_url).rstrip('/')}/models?pageSize=50"
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
                str(m.get("name", "")).removeprefix("models/")
                for m in (body.get("models") or [])
                if isinstance(m, dict) and m.get("name")
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
                error_message=f"Gemini API unreachable ({type(exc).__name__})",
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
        model_path = model_id.removeprefix("models/")
        headers = self._headers(api_key)
        started = time.perf_counter()

        try:
            async with self._build_http_client(20.0) as client:
                if deep_inference:
                    resp = await client.post(
                        f"{root}/models/{model_path}:generateContent",
                        headers=headers,
                        json={
                            "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                            "generationConfig": {"maxOutputTokens": 4, "temperature": 0},
                        },
                    )
                    scope = "model_inference"
                else:
                    resp = await client.get(
                        f"{root}/models/{model_path}", headers=headers
                    )
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
                error_message=f"Gemini model probe failed ({type(exc).__name__})",
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
