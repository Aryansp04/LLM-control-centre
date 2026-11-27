"""Pydantic v2 Request and Response Schemas for REST & WebSocket APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Auth Schemas
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    username: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


# ---------------------------------------------------------------------------
# Provider & Model Schemas
# ---------------------------------------------------------------------------
class ProviderUpdateCredentialsRequest(BaseModel):
    api_key: Optional[str] = Field(default=None, max_length=512)
    clear_api_key: bool = False
    base_url_override: Optional[str] = Field(default=None, max_length=500)
    organization_id: Optional[str] = Field(default=None, max_length=150)
    is_enabled: Optional[bool] = None
    verify_immediately: bool = True

    @field_validator("base_url_override")
    @classmethod
    def validate_base_url(cls, val: Optional[str]) -> Optional[str]:
        if val is None or not val.strip():
            return None
        cleaned = val.strip()
        if not cleaned.startswith(("https://", "http://")):
            raise ValueError("Base URL override must start with https:// or http://")
        return cleaned


class ProviderResponse(BaseModel):
    id: str
    provider_key: str
    display_name: str
    has_api_key: bool
    credential_source: str  # "user_vault" | "server_env" | "none"
    key_hint: Optional[str] = None
    base_url_override: Optional[str] = None
    organization_id: Optional[str] = None
    is_enabled: bool
    status: str
    account_status: str
    last_checked_at: Optional[datetime] = None
    last_latency_ms: Optional[float] = None
    last_error: Optional[str] = None
    capabilities: Dict[str, Any]
    model_count: int = 0
    quota: Optional[Dict[str, Any]] = None


class ModelCreateCustomRequest(BaseModel):
    provider_key: str = Field(min_length=2, max_length=50)
    model_id: str = Field(min_length=2, max_length=150)
    display_name: str = Field(min_length=2, max_length=150)
    description: Optional[str] = Field(default=None, max_length=500)
    context_window: int = Field(default=128000, ge=1024, le=4000000)
    max_output_tokens: int = Field(default=8192, ge=64, le=256000)
    supports_streaming: bool = True
    supports_system_instruction: bool = True
    supports_temperature: bool = True
    supports_max_tokens: bool = True
    supports_vision: bool = False
    supports_file_attachments: bool = True
    input_price_per_1m: Optional[float] = Field(default=None, ge=0)
    output_price_per_1m: Optional[float] = Field(default=None, ge=0)


class ModelResponse(BaseModel):
    id: str
    provider_id: str
    provider_key: str
    provider_name: str
    model_id: str
    display_name: str
    description: Optional[str] = None
    context_window: int
    max_output_tokens: int
    supports_streaming: bool
    supports_system_instruction: bool
    supports_temperature: bool
    supports_max_tokens: bool
    supports_vision: bool
    supports_file_attachments: bool
    input_price_per_1m: Optional[float] = None
    output_price_per_1m: Optional[float] = None
    pricing_version: str
    status: str
    provider_status: str
    account_status: str
    has_credentials: bool
    is_available: bool
    last_checked_at: Optional[datetime] = None
    last_latency_ms: Optional[float] = None
    last_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Conversation & Chat Schemas
# ---------------------------------------------------------------------------
class AttachmentInputSchema(BaseModel):
    filename: str = Field(min_length=1, max_length=150)
    content_type: str = Field(default="text/plain", max_length=100)
    base64_content: str = Field(min_length=1)


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    provider_key: str = Field(default="openai", max_length=50)
    model_id: str = Field(default="gpt-4o-mini", max_length=150)
    system_instruction: Optional[str] = Field(default=None, max_length=16000)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: Optional[int] = Field(default=None, ge=16, le=128000)


class ConversationUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    active_provider: Optional[str] = Field(default=None, max_length=50)
    active_model: Optional[str] = Field(default=None, max_length=150)
    system_instruction: Optional[str] = Field(default=None, max_length=16000)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: Optional[int] = Field(default=None, ge=16, le=128000)
    is_pinned: Optional[bool] = None


class ChatRequestPayload(BaseModel):
    conversation_id: Optional[str] = None
    provider_key: str = Field(min_length=2, max_length=50)
    model_id: str = Field(min_length=1, max_length=150)
    message: str = Field(default="", max_length=120000)
    system_instruction: Optional[str] = Field(default=None, max_length=16000)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: Optional[int] = Field(default=None, ge=1, le=128000)
    attachments: List[AttachmentInputSchema] = Field(default_factory=list, max_length=5)
    regenerate_from_message_id: Optional[str] = None


class CancelGenerationRequest(BaseModel):
    stream_id: str = Field(min_length=4, max_length=100)


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    provider_key: Optional[str] = None
    requested_model: Optional[str] = None
    actual_model_used: Optional[str] = None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: Optional[float] = None
    ttft_ms: Optional[float] = None
    tokens_per_second: Optional[float] = None
    estimated_cost_usd: Optional[float] = None
    status: str
    error_message: Optional[str] = None
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ConversationSummaryResponse(BaseModel):
    id: str
    title: str
    active_provider: str
    active_model: str
    system_instruction: Optional[str] = None
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_estimated_cost_usd: float
    message_count: int
    is_pinned: bool
    last_message_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationSummaryResponse):
    messages: List[MessageResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Monitoring & Settings Schemas
# ---------------------------------------------------------------------------
class MonitoringCheckRequest(BaseModel):
    provider_key: Optional[str] = None
    model_id: Optional[str] = None
    deep_inference: bool = False


class UserSettingsUpdateRequest(BaseModel):
    workspace_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    default_provider: Optional[str] = Field(default=None, max_length=50)
    default_model: Optional[str] = Field(default=None, max_length=150)
    default_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    default_max_tokens: Optional[int] = Field(default=None, ge=64, le=128000)
    default_system_instruction: Optional[str] = Field(default=None, max_length=16000)
    context_max_tokens_ratio: Optional[float] = Field(default=None, ge=0.3, le=0.95)
    auto_monitoring_enabled: Optional[bool] = None
    monitoring_interval_seconds: Optional[int] = Field(default=None, ge=30, le=3600)
    enable_deep_model_probe: Optional[bool] = None
    notifications_enabled: Optional[bool] = None
