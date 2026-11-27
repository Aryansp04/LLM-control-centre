"""Abstract provider adapter with retry/backoff, cancellation, and token estimation fallback."""

from __future__ import annotations

import abc
import asyncio
from contextlib import asynccontextmanager
import logging
import math
import random
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

import httpx

from app.config import get_settings
from app.providers.types import (
    ChatMessageInput,
    GenerationCancelledError,
    GenerationRequest,
    GenerationResult,
    HealthProbeResult,
    ModelSpec,
    ProviderAuthenticationError,
    ProviderBadRequestError,
    ProviderCapabilities,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StreamChunk,
)

logger = logging.getLogger(__name__)


def estimate_tokens_fallback(text: str) -> int:
    """Deterministic fallback token estimator (~4 chars/token) used ONLY when a provider
    omits token counts (e.g. cancelled mid-stream before final usage frame)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def format_message_with_text_attachments(msg: ChatMessageInput) -> str:
    """Inline extracted text/PDF attachments cleanly into the prompt body."""
    parts: List[str] = []
    if msg.content:
        parts.append(msg.content)
    for att in msg.attachments:
        if att.extracted_text:
            parts.append(
                f"\n\n--- Attached File: {att.filename} ({att.mime_type}) ---\n"
                f"{att.extracted_text}\n--- End of {att.filename} ---"
            )
    return "\n".join(parts).strip()


_SHARED_HTTP_CLIENTS: Dict[Tuple[int, float], httpx.AsyncClient] = {}


class BaseProviderAdapter(abc.ABC):
    provider_key: str
    display_name: str
    default_base_url: str

    def __init__(self, http_transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._transport = http_transport

    @asynccontextmanager
    async def _build_http_client(self, timeout_seconds: float = 60.0) -> AsyncIterator[httpx.AsyncClient]:
        timeout = httpx.Timeout(timeout_seconds, connect=8.0)
        if self._transport is not None:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as test_client:
                yield test_client
            return

        loop_id = id(asyncio.get_running_loop())
        key = (loop_id, float(timeout_seconds))
        shared = _SHARED_HTTP_CLIENTS.get(key)
        if shared is None or shared.is_closed:
            shared = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(
                    max_keepalive_connections=20,
                    max_connections=60,
                    keepalive_expiry=45.0,
                ),
            )
            _SHARED_HTTP_CLIENTS[key] = shared
        yield shared

    @abc.abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    @abc.abstractmethod
    def get_default_models(self) -> List[ModelSpec]:
        raise NotImplementedError

    def get_model_spec(self, model_id: str) -> Optional[ModelSpec]:
        for spec in self.get_default_models():
            if spec.model_id == model_id:
                return spec
        return None

    @abc.abstractmethod
    async def complete(
        self,
        request: GenerationRequest,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        organization_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> GenerationResult:
        raise NotImplementedError

    @abc.abstractmethod
    def stream(
        self,
        request: GenerationRequest,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        organization_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError

    @abc.abstractmethod
    async def probe_provider_and_account(
        self,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> HealthProbeResult:
        raise NotImplementedError

    @abc.abstractmethod
    async def probe_model(
        self,
        api_key: str,
        model_id: str,
        *,
        deep_inference: bool = False,
        base_url: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> HealthProbeResult:
        raise NotImplementedError

    def classify_http_error(
        self, status_code: int, body_data: Any, headers: httpx.Headers
    ) -> ProviderError:
        """Normalize provider-specific HTTP errors without leaking headers or keys."""
        msg = self._extract_error_message(body_data) or f"HTTP {status_code} from {self.display_name}"
        retry_after: Optional[float] = None
        ra_header = headers.get("retry-after")
        if ra_header:
            try:
                retry_after = float(ra_header)
            except ValueError:
                retry_after = None

        lowered = msg.lower()
        if status_code in (401, 403) or "api key not valid" in lowered or "invalid x-api-key" in lowered:
            return ProviderAuthenticationError(
                msg, provider_key=self.provider_key, status_code=status_code
            )
        is_quota = (
            "insufficient_quota" in lowered
            or "no credits remaining" in lowered
            or "credit balance is too low" in lowered
        )
        if is_quota or status_code == 429:
            return ProviderRateLimitError(
                msg,
                provider_key=self.provider_key,
                status_code=status_code,
                retry_after=retry_after,
                is_quota=is_quota or ("billing" in lowered and status_code == 429),
            )
        if status_code in (500, 502, 503, 504, 529):
            return ProviderUnavailableError(
                msg, provider_key=self.provider_key, status_code=status_code
            )
        return ProviderBadRequestError(
            msg, provider_key=self.provider_key, status_code=status_code
        )

    @staticmethod
    def _extract_error_message(body_data: Any) -> str:
        if isinstance(body_data, dict):
            err = body_data.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err.get("status") or err)
            if isinstance(err, str):
                return err
            if "message" in body_data:
                return str(body_data["message"])
        if isinstance(body_data, str):
            return body_data[:400]
        return ""

    async def _sleep_with_cancel(
        self, delay: float, cancel_event: Optional[asyncio.Event]
    ) -> None:
        if cancel_event is None:
            await asyncio.sleep(delay)
            return
        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=delay)
            raise GenerationCancelledError("Generation cancelled during retry backoff")
        except asyncio.TimeoutError:
            return

    async def execute_with_retry(
        self,
        operation: Callable[[], Any],
        *,
        max_retries: Optional[int] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> tuple[Any, int]:
        """Run an async provider call with exponential backoff + jitter on retryable failures."""
        settings = get_settings()
        retries = settings.provider_max_retries if max_retries is None else max_retries
        attempt = 0

        while True:
            if cancel_event and cancel_event.is_set():
                raise GenerationCancelledError("Generation cancelled before request")
            try:
                result = await operation()
                return result, attempt
            except GenerationCancelledError:
                raise
            except ProviderError as exc:
                if not exc.retryable or attempt >= retries:
                    raise
                delay = (
                    min(exc.retry_after, 8.0)
                    if exc.retry_after
                    else min(0.6 * (2**attempt) + random.uniform(0.05, 0.25), 6.0)
                )
                attempt += 1
                logger.warning(
                    "Retrying %s after %s (attempt %d/%d, delay %.2fs)",
                    self.provider_key,
                    exc.error_type,
                    attempt,
                    retries,
                    delay,
                )
                await self._sleep_with_cancel(delay, cancel_event)
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                if attempt >= retries:
                    raise ProviderTimeoutError(
                        f"{self.display_name} request timed out ({type(exc).__name__})",
                        provider_key=self.provider_key,
                    ) from exc
                delay = min(0.6 * (2**attempt) + random.uniform(0.05, 0.25), 6.0)
                attempt += 1
                await self._sleep_with_cancel(delay, cancel_event)
            except httpx.RequestError as exc:
                if attempt >= retries:
                    raise ProviderUnavailableError(
                        f"Network error contacting {self.display_name} ({type(exc).__name__})",
                        provider_key=self.provider_key,
                    ) from exc
                delay = min(0.6 * (2**attempt) + random.uniform(0.05, 0.25), 6.0)
                attempt += 1
                await self._sleep_with_cancel(delay, cancel_event)
