"""Unified types, capability descriptors, and error hierarchy for LLM providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ProviderCapabilities:
    provider_key: str
    display_name: str
    supports_streaming: bool = True
    supports_system_instruction: bool = True
    supports_temperature: bool = True
    min_temperature: float = 0.0
    max_temperature: float = 2.0
    supports_max_tokens: bool = True
    supports_vision: bool = True
    supports_file_attachments: bool = True
    supports_model_listing: bool = True
    official_docs_url: str = ""


@dataclass(frozen=True)
class ModelSpec:
    provider_key: str
    model_id: str
    display_name: str
    description: str
    context_window: int
    max_output_tokens: int
    supports_streaming: bool = True
    supports_system_instruction: bool = True
    supports_temperature: bool = True
    supports_max_tokens: bool = True
    supports_vision: bool = False
    supports_file_attachments: bool = True
    input_price_per_1m: Optional[Decimal] = None
    output_price_per_1m: Optional[Decimal] = None
    pricing_version: str = "2026.11-official-v1"


@dataclass
class AttachmentPayload:
    filename: str
    mime_type: str
    size_bytes: int
    kind: str  # "text" | "image" | "pdf"
    extracted_text: Optional[str] = None
    base64_data: Optional[str] = None


@dataclass
class ChatMessageInput:
    role: str  # "user" | "assistant" | "system"
    content: str
    attachments: List[AttachmentPayload] = field(default_factory=list)


@dataclass
class GenerationRequest:
    model: str
    messages: List[ChatMessageInput]
    system_instruction: Optional[str] = None
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    stream: bool = True
    timeout_seconds: float = 60.0


@dataclass
class StreamChunk:
    delta_text: str = ""
    actual_model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    is_final: bool = False


@dataclass
class GenerationResult:
    content: str
    actual_model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    ttft_ms: Optional[float]
    tokens_per_second: Optional[float]
    retry_count: int = 0
    finish_reason: Optional[str] = "stop"


@dataclass
class HealthProbeResult:
    provider_key: str
    check_scope: str  # "provider_auth" | "model_availability" | "model_inference"
    provider_status: str  # "operational" | "degraded" | "unavailable" | "unknown"
    account_status: str  # "unconfigured" | "configured" | "verified" | "invalid_credentials" | "rate_limited" | "quota_exceeded"
    model_status: Optional[str] = None  # "configured" | "reachable" | "request_successful" | "request_failed" | "rate_limited"
    model_id: Optional[str] = None
    is_healthy: bool = False
    latency_ms: Optional[float] = None
    http_status_code: Optional[int] = None
    error_message: Optional[str] = None
    discovered_model_ids: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provider Error Hierarchy
# ---------------------------------------------------------------------------
class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        provider_key: str,
        status_code: Optional[int] = None,
        error_type: str = "provider_error",
        retryable: bool = False,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.provider_key = provider_key
        self.status_code = status_code
        self.error_type = error_type
        self.retryable = retryable
        self.retry_after = retry_after


class ProviderAuthenticationError(ProviderError):
    def __init__(
        self, message: str, *, provider_key: str, status_code: Optional[int] = 401
    ) -> None:
        super().__init__(
            message,
            provider_key=provider_key,
            status_code=status_code,
            error_type="invalid_credentials",
            retryable=False,
        )


class ProviderRateLimitError(ProviderError):
    def __init__(
        self,
        message: str,
        *,
        provider_key: str,
        status_code: int = 429,
        retry_after: Optional[float] = None,
        is_quota: bool = False,
    ) -> None:
        super().__init__(
            message,
            provider_key=provider_key,
            status_code=status_code,
            error_type="quota_exceeded" if is_quota else "rate_limited",
            retryable=not is_quota,
            retry_after=retry_after,
        )


class ProviderTimeoutError(ProviderError):
    def __init__(self, message: str, *, provider_key: str) -> None:
        super().__init__(
            message,
            provider_key=provider_key,
            status_code=504,
            error_type="timeout",
            retryable=True,
        )


class ProviderUnavailableError(ProviderError):
    def __init__(
        self, message: str, *, provider_key: str, status_code: Optional[int] = 503
    ) -> None:
        super().__init__(
            message,
            provider_key=provider_key,
            status_code=status_code,
            error_type="provider_unavailable",
            retryable=True,
        )


class ProviderBadRequestError(ProviderError):
    def __init__(
        self, message: str, *, provider_key: str, status_code: Optional[int] = 400
    ) -> None:
        super().__init__(
            message,
            provider_key=provider_key,
            status_code=status_code,
            error_type="bad_request",
            retryable=False,
        )


class GenerationCancelledError(Exception):
    """Raised when a client cancels an active generation."""
