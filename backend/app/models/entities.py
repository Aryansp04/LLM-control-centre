"""10 Normalized PostgreSQL Entities for LLM Control Center.

Entities:
1. User (users)
2. Provider (providers)
3. LLMModel (models)
4. Conversation (conversations)
5. Message (messages)
6. APIRequest (api_requests)
7. ModelHealthCheck (model_health_checks)
8. UsageRecord (usage_records)
9. MonitoringEvent (monitoring_events)
10. UserSettings (user_settings)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    username: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="admin", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    providers: Mapped[List["Provider"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    models: Mapped[List["LLMModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped[Optional["UserSettings"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# 2. Providers
# ---------------------------------------------------------------------------
class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (
        UniqueConstraint("user_id", "provider_key", name="uq_providers_user_provider"),
        Index("ix_providers_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_hint: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    base_url_override: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Provider-level health: operational | degraded | unavailable | unknown
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    # Account-level access: unconfigured | configured | verified | invalid_credentials | rate_limited | quota_exceeded
    account_status: Mapped[str] = mapped_column(
        String(40), default="unconfigured", nullable=False
    )
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    capabilities_json: Mapped[Dict[str, Any]] = mapped_column(
        JSONVariant, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="providers")
    models: Mapped[List["LLMModel"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )
    health_checks: Mapped[List["ModelHealthCheck"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# 3. Models
# ---------------------------------------------------------------------------
class LLMModel(Base):
    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider_key", "model_id", name="uq_models_user_provider_model"
        ),
        Index("ix_models_user_provider", "user_id", "provider_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String(150), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context_window: Mapped[int] = mapped_column(Integer, default=128000, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=8192, nullable=False)

    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_system_instruction: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    supports_temperature: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    supports_max_tokens: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_file_attachments: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # Versioned pricing (USD per 1M tokens; nullable if pricing unknown)
    input_price_per_1m: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    output_price_per_1m: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    pricing_version: Mapped[str] = mapped_column(
        String(50), default="2026.11-official-v1", nullable=False
    )

    # Model-specific status: unconfigured | configured | reachable | request_successful | request_failed | rate_limited
    status: Mapped[str] = mapped_column(
        String(40), default="unconfigured", nullable=False
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="models")
    provider: Mapped["Provider"] = relationship(back_populates="models")


# ---------------------------------------------------------------------------
# 4. Conversations
# ---------------------------------------------------------------------------
class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    active_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    active_model: Mapped[str] = mapped_column(String(150), nullable=False)
    system_instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 8), default=Decimal("0"), nullable=False
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


# ---------------------------------------------------------------------------
# 5. Messages
# ---------------------------------------------------------------------------
class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provider_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    requested_model: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    actual_model_used: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ttft_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tokens_per_second: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_cost_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 8), nullable=True
    )

    # streaming | completed | cancelled | failed
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attachments_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONVariant, nullable=True
    )
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONVariant, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# 6. API Requests
# ---------------------------------------------------------------------------
class APIRequest(Base):
    __tablename__ = "api_requests"
    __table_args__ = (
        Index("ix_api_requests_user_created", "user_id", "created_at"),
        Index("ix_api_requests_user_provider_status", "user_id", "provider_key", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    request_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_key: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    requested_model: Mapped[str] = mapped_column(String(150), index=True, nullable=False)
    actual_model_used: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    endpoint_type: Mapped[str] = mapped_column(String(40), nullable=False)
    is_streaming: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # success | failed | cancelled | rate_limited | timeout
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    http_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    ttft_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tokens_per_second: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 8), nullable=True
    )
    pricing_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )


# ---------------------------------------------------------------------------
# 7. Model Health Checks
# ---------------------------------------------------------------------------
class ModelHealthCheck(Base):
    __tablename__ = "model_health_checks"
    __table_args__ = (
        Index("ix_health_checks_user_checked", "user_id", "checked_at"),
        Index("ix_health_checks_provider_model", "provider_key", "model_id", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    model_db_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("models.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    provider_key: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    model_id: Mapped[Optional[str]] = mapped_column(String(150), index=True, nullable=True)

    # provider_auth | model_availability | model_inference
    check_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_status: Mapped[str] = mapped_column(String(32), nullable=False)
    account_status: Mapped[str] = mapped_column(String(40), nullable=False)
    model_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    is_healthy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    http_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONVariant, nullable=True
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )

    provider: Mapped["Provider"] = relationship(back_populates="health_checks")


# ---------------------------------------------------------------------------
# 8. Usage Records
# ---------------------------------------------------------------------------
class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_user_recorded", "user_id", "recorded_at"),
        Index(
            "ix_usage_records_user_provider_model",
            "user_id",
            "provider_key",
            "model_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    api_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("api_requests.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    provider_key: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String(150), index=True, nullable=False)
    request_status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_unit_price_per_1m: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    output_unit_price_per_1m: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    estimated_cost_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 8), nullable=True
    )
    is_cost_estimated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(50), nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )


# ---------------------------------------------------------------------------
# 9. Monitoring Events
# ---------------------------------------------------------------------------
class MonitoringEvent(Base):
    __tablename__ = "monitoring_events"
    __table_args__ = (
        Index("ix_monitoring_events_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="info", nullable=False)
    provider_key: Mapped[Optional[str]] = mapped_column(
        String(50), index=True, nullable=True
    )
    model_id: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONVariant, nullable=True
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )


# ---------------------------------------------------------------------------
# 10. User Settings
# ---------------------------------------------------------------------------
class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    workspace_name: Mapped[str] = mapped_column(
        String(120), default="Production AI Workspace", nullable=False
    )
    default_provider: Mapped[str] = mapped_column(
        String(50), default="openai", nullable=False
    )
    default_model: Mapped[str] = mapped_column(
        String(150), default="gpt-4o-mini", nullable=False
    )
    default_temperature: Mapped[float] = mapped_column(
        Float, default=0.7, nullable=False
    )
    default_max_tokens: Mapped[int] = mapped_column(
        Integer, default=2048, nullable=False
    )
    default_system_instruction: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    context_max_tokens_ratio: Mapped[float] = mapped_column(
        Float, default=0.8, nullable=False
    )
    auto_monitoring_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    monitoring_interval_seconds: Mapped[int] = mapped_column(
        Integer, default=180, nullable=False
    )
    enable_deep_model_probe: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="settings")
