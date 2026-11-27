"""Application configuration loaded from environment variables with strict validation."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
IS_VERCEL = bool(os.getenv("VERCEL"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "LLM Control Center"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Security
    jwt_secret_key: str = Field(
        default="dev-jwt-secret-replace-in-production-with-64-byte-random-key-0123456789"
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 720
    encryption_secret_key: str = Field(
        default="dev-encryption-secret-replace-in-production-32bytes-key"
    )

    # HTTP & Rate Limiting
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
    max_request_body_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_attachment_bytes: int = 5 * 1024 * 1024  # 5 MB per file
    rate_limit_requests_per_minute: int = 90
    auth_rate_limit_per_minute: int = 20

    # Database & Redis
    database_url: str = (
        "postgresql+asyncpg://llmcc:llmcc_password@localhost:5432/llm_control_center"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    redis_url: str = "redis://localhost:6379/0"

    # Optional server-level provider fallback keys (NEVER exposed to frontend)
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    # Provider HTTP & Monitoring
    background_monitoring_enabled: bool = True
    background_monitoring_interval_seconds: int = 180
    provider_http_timeout_seconds: float = 60.0
    provider_max_retries: int = 2

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        val = value.strip()
        if val.startswith("postgres://"):
            val = "postgresql+asyncpg://" + val[len("postgres://") :]
        elif val.startswith("postgresql://") and "+asyncpg" not in val:
            val = "postgresql+asyncpg://" + val[len("postgresql://") :]

        # Convert libpq sslmode/channel_binding query params to asyncpg-compatible params
        if val.startswith("postgresql+asyncpg://") and "?" in val:
            parts = urlsplit(val)
            raw_params = parse_qsl(parts.query, keep_blank_values=True)
            cleaned_params = []
            for k, v in raw_params:
                if k == "sslmode":
                    if v != "disable":
                        cleaned_params.append(("ssl", "require"))
                elif k == "channel_binding":
                    continue
                else:
                    cleaned_params.append((k, v))
            val = urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(cleaned_params), parts.fragment)
            )
        return val

    @model_validator(mode="after")
    def apply_vercel_serverless_defaults(self) -> "Settings":
        if IS_VERCEL:
            # Support Vercel Postgres / Neon `POSTGRES_URL` automatically
            pg_env = os.getenv("POSTGRES_URL") or os.getenv("POSTGRES_PRISMA_URL")
            if pg_env and not os.getenv("DATABASE_URL"):
                self.database_url = self.normalize_database_url(pg_env)
            elif not os.getenv("DATABASE_URL") and "localhost" in self.database_url:
                self.database_url = "sqlite+aiosqlite:////tmp/llm_control_center.db"

            # Support Vercel KV / Upstash `KV_URL` automatically, or safe memory fallback
            kv_env = os.getenv("KV_URL")
            if kv_env and not os.getenv("REDIS_URL"):
                self.redis_url = kv_env
            elif not os.getenv("REDIS_URL") and "localhost" in self.redis_url:
                self.redis_url = "memory://vercel"

            # Serverless invocations must not spawn infinite background loops
            self.background_monitoring_enabled = False
        return self

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
