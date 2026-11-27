"""Initial schema creating all 10 normalized entities, indexes, and foreign keys.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-26 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # 2. providers
    op.create_table(
        "providers",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_key", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("key_hint", sa.String(length=32), nullable=True),
        sa.Column("base_url_override", sa.String(length=500), nullable=True),
        sa.Column("organization_id", sa.String(length=150), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column(
            "account_status",
            sa.String(length=40),
            nullable=False,
            server_default="unconfigured",
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_latency_ms", sa.Float(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("capabilities_json", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "provider_key", name="uq_providers_user_provider"),
    )
    op.create_index("ix_providers_user_id", "providers", ["user_id"])
    op.create_index("ix_providers_provider_key", "providers", ["provider_key"])
    op.create_index("ix_providers_user_status", "providers", ["user_id", "status"])

    # 3. models
    op.create_table(
        "models",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_key", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=150), nullable=False),
        sa.Column("display_name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "supports_system_instruction",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("supports_temperature", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("supports_max_tokens", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "supports_file_attachments",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("input_price_per_1m", sa.Numeric(12, 6), nullable=True),
        sa.Column("output_price_per_1m", sa.Numeric(12, 6), nullable=True),
        sa.Column("pricing_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="unconfigured"),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_latency_ms", sa.Float(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "provider_key", "model_id", name="uq_models_user_provider_model"
        ),
    )
    op.create_index("ix_models_user_id", "models", ["user_id"])
    op.create_index("ix_models_provider_id", "models", ["provider_id"])
    op.create_index("ix_models_provider_key", "models", ["provider_key"])
    op.create_index("ix_models_model_id", "models", ["model_id"])
    op.create_index("ix_models_user_provider", "models", ["user_id", "provider_key"])

    # 4. conversations
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("active_provider", sa.String(length=50), nullable=False),
        sa.Column("active_model", sa.String(length=150), nullable=False),
        sa.Column("system_instruction", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_estimated_cost_usd", sa.Numeric(14, 8), nullable=False, server_default="0"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_title", "conversations", ["title"])
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])
    op.create_index("ix_conversations_user_updated", "conversations", ["user_id", "updated_at"])

    # 5. messages
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider_key", sa.String(length=50), nullable=True),
        sa.Column("requested_model", sa.String(length=150), nullable=True),
        sa.Column("actual_model_used", sa.String(length=150), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("tokens_per_second", sa.Float(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(14, 8), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attachments_json", JSONType, nullable=True),
        sa.Column("metadata_json", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_user_id", "messages", ["user_id"])
    op.create_index("ix_messages_conv_created", "messages", ["conversation_id", "created_at"])

    # 6. api_requests
    op.create_table(
        "api_requests",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider_key", sa.String(length=50), nullable=False),
        sa.Column("requested_model", sa.String(length=150), nullable=False),
        sa.Column("actual_model_used", sa.String(length=150), nullable=True),
        sa.Column("endpoint_type", sa.String(length=40), nullable=False),
        sa.Column("is_streaming", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("tokens_per_second", sa.Float(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Numeric(14, 8), nullable=True),
        sa.Column("pricing_version", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_requests_request_id", "api_requests", ["request_id"], unique=True)
    op.create_index("ix_api_requests_user_id", "api_requests", ["user_id"])
    op.create_index("ix_api_requests_conversation_id", "api_requests", ["conversation_id"])
    op.create_index("ix_api_requests_provider_key", "api_requests", ["provider_key"])
    op.create_index("ix_api_requests_requested_model", "api_requests", ["requested_model"])
    op.create_index("ix_api_requests_status", "api_requests", ["status"])
    op.create_index("ix_api_requests_created_at", "api_requests", ["created_at"])
    op.create_index("ix_api_requests_user_created", "api_requests", ["user_id", "created_at"])
    op.create_index(
        "ix_api_requests_user_provider_status",
        "api_requests",
        ["user_id", "provider_key", "status"],
    )

    # 7. model_health_checks
    op.create_table(
        "model_health_checks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_db_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("models.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("provider_key", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=150), nullable=True),
        sa.Column("check_scope", sa.String(length=40), nullable=False),
        sa.Column("provider_status", sa.String(length=32), nullable=False),
        sa.Column("account_status", sa.String(length=40), nullable=False),
        sa.Column("model_status", sa.String(length=40), nullable=True),
        sa.Column("is_healthy", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details_json", JSONType, nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_health_checks_user_id", "model_health_checks", ["user_id"])
    op.create_index("ix_model_health_checks_provider_id", "model_health_checks", ["provider_id"])
    op.create_index("ix_model_health_checks_model_db_id", "model_health_checks", ["model_db_id"])
    op.create_index("ix_model_health_checks_provider_key", "model_health_checks", ["provider_key"])
    op.create_index("ix_model_health_checks_model_id", "model_health_checks", ["model_id"])
    op.create_index("ix_model_health_checks_checked_at", "model_health_checks", ["checked_at"])
    op.create_index(
        "ix_health_checks_user_checked", "model_health_checks", ["user_id", "checked_at"]
    )
    op.create_index(
        "ix_health_checks_provider_model",
        "model_health_checks",
        ["provider_key", "model_id", "checked_at"],
    )

    # 8. usage_records
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "api_request_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("api_requests.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider_key", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=150), nullable=False),
        sa.Column("request_status", sa.String(length=32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_unit_price_per_1m", sa.Numeric(12, 6), nullable=True),
        sa.Column("output_unit_price_per_1m", sa.Numeric(12, 6), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(14, 8), nullable=True),
        sa.Column("is_cost_estimated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("pricing_version", sa.String(length=50), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_records_user_id", "usage_records", ["user_id"])
    op.create_index("ix_usage_records_conversation_id", "usage_records", ["conversation_id"])
    op.create_index("ix_usage_records_provider_key", "usage_records", ["provider_key"])
    op.create_index("ix_usage_records_model_id", "usage_records", ["model_id"])
    op.create_index("ix_usage_records_request_status", "usage_records", ["request_status"])
    op.create_index("ix_usage_records_recorded_at", "usage_records", ["recorded_at"])
    op.create_index(
        "ix_usage_records_user_recorded", "usage_records", ["user_id", "recorded_at"]
    )
    op.create_index(
        "ix_usage_records_user_provider_model",
        "usage_records",
        ["user_id", "provider_key", "model_id"],
    )

    # 9. monitoring_events
    op.create_table(
        "monitoring_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("provider_key", sa.String(length=50), nullable=True),
        sa.Column("model_id", sa.String(length=150), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_json", JSONType, nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_monitoring_events_user_id", "monitoring_events", ["user_id"])
    op.create_index("ix_monitoring_events_event_type", "monitoring_events", ["event_type"])
    op.create_index("ix_monitoring_events_provider_key", "monitoring_events", ["provider_key"])
    op.create_index("ix_monitoring_events_created_at", "monitoring_events", ["created_at"])
    op.create_index(
        "ix_monitoring_events_user_created", "monitoring_events", ["user_id", "created_at"]
    )

    # 10. user_settings
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "workspace_name",
            sa.String(length=120),
            nullable=False,
            server_default="Production AI Workspace",
        ),
        sa.Column("default_provider", sa.String(length=50), nullable=False, server_default="openai"),
        sa.Column(
            "default_model", sa.String(length=150), nullable=False, server_default="gpt-4o-mini"
        ),
        sa.Column("default_temperature", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("default_max_tokens", sa.Integer(), nullable=False, server_default="2048"),
        sa.Column("default_system_instruction", sa.Text(), nullable=True),
        sa.Column("context_max_tokens_ratio", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column(
            "auto_monitoring_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "monitoring_interval_seconds", sa.Integer(), nullable=False, server_default="180"
        ),
        sa.Column(
            "enable_deep_model_probe", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_settings_user_id", "user_settings", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_table("monitoring_events")
    op.drop_table("usage_records")
    op.drop_table("model_health_checks")
    op.drop_table("api_requests")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("models")
    op.drop_table("providers")
    op.drop_table("users")
