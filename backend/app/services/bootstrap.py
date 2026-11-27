"""User workspace bootstrapper and server-side API credential resolver."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import decrypt_api_key, mask_api_key
from app.models.entities import LLMModel, Provider, User, UserSettings
from app.providers.registry import provider_registry

_loop_locks: Dict[int, asyncio.Lock] = {}
_initialized_users: set[str] = set()


def get_loop_bootstrap_lock() -> asyncio.Lock:
    loop_id = id(asyncio.get_running_loop())
    lock = _loop_locks.get(loop_id)
    if lock is None:
        lock = asyncio.Lock()
        _loop_locks[loop_id] = lock
    return lock


def get_system_env_api_key(provider_key: str) -> Optional[str]:
    """Read optional server-side fallback API key from environment (NEVER exposed to clients)."""
    settings = get_settings()
    key_map = {
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
        "anthropic": settings.anthropic_api_key,
    }
    raw = (key_map.get(provider_key.lower()) or "").strip()
    return raw if raw else None


def resolve_provider_api_key(provider: Provider) -> Tuple[Optional[str], str]:
    """Return `(plain_api_key, source)` where source is `'user_vault'`, `'server_env'`, or `'none'`."""
    if provider.encrypted_api_key:
        return decrypt_api_key(provider.encrypted_api_key), "user_vault"
    env_key = get_system_env_api_key(provider.provider_key)
    if env_key:
        return env_key, "server_env"
    return None, "none"


async def ensure_user_workspace_initialized(
    db: AsyncSession, user: User, *, force_sync: bool = False
) -> None:
    """Idempotently seed UserSettings, Providers, and default LLMModels for `user` with O(1) cache."""
    cache_key = f"{id(db.bind)}:{user.id}"
    if not force_sync and cache_key in _initialized_users:
        return

    async with get_loop_bootstrap_lock():
        if not force_sync and cache_key in _initialized_users:
            return
        if not force_sync:
            # Fast single-column check to avoid 4 full SELECTs + COMMIT on already-seeded workspaces
            existing_prov_id = (
                await db.execute(
                    select(Provider.id).where(Provider.user_id == user.id).limit(1)
                )
            ).scalar_one_or_none()
            if existing_prov_id is not None:
                _initialized_users.add(cache_key)
                return

        try:
            await _seed_user_workspace(db, user)
            await db.commit()
            _initialized_users.add(cache_key)
        except IntegrityError:
            await db.rollback()
            _initialized_users.add(cache_key)


async def _seed_user_workspace(db: AsyncSession, user: User) -> None:
    # 1. Settings
    default_prov = "gemini" if get_system_env_api_key("gemini") else "openai"
    default_mod = (
        "gemini-3.1-flash-lite-preview" if default_prov == "gemini" else "gpt-4o-mini"
    )
    settings_res = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    user_settings_row = settings_res.scalar_one_or_none()
    if user_settings_row is None:
        db.add(
            UserSettings(
                user_id=user.id,
                workspace_name=f"{user.username}'s Control Center",
                default_provider=default_prov,
                default_model=default_mod,
            )
        )
    elif (
        default_prov == "gemini"
        and user_settings_row.default_provider == "openai"
        and not get_system_env_api_key("openai")
    ):
        user_settings_row.default_provider = "gemini"
        user_settings_row.default_model = "gemini-3.1-flash-lite-preview"

    # 2. Providers & Default Models
    prov_res = await db.execute(select(Provider).where(Provider.user_id == user.id))
    existing_providers = {p.provider_key: p for p in prov_res.scalars().all()}

    model_res = await db.execute(select(LLMModel).where(LLMModel.user_id == user.id))
    existing_models = {
        (m.provider_key, m.model_id): m for m in model_res.scalars().all()
    }

    for adapter in provider_registry.list_adapters():
        caps = adapter.get_capabilities()
        env_key = get_system_env_api_key(adapter.provider_key)
        provider_row = existing_providers.get(adapter.provider_key)

        if provider_row is None:
            has_env = bool(env_key)
            provider_row = Provider(
                user_id=user.id,
                provider_key=adapter.provider_key,
                display_name=adapter.display_name,
                key_hint=mask_api_key(env_key) if env_key else None,
                is_enabled=True,
                status="operational" if has_env else "unknown",
                account_status="verified" if has_env else "unconfigured",
                capabilities_json=asdict(caps),
            )
            db.add(provider_row)
            await db.flush()
            existing_providers[adapter.provider_key] = provider_row
        else:
            provider_row.capabilities_json = asdict(caps)
            if not provider_row.encrypted_api_key and env_key:
                provider_row.key_hint = mask_api_key(env_key)
                if provider_row.account_status in ("unconfigured", "configured"):
                    provider_row.account_status = "verified"
                if provider_row.status == "unknown":
                    provider_row.status = "operational"

        has_credentials = bool(provider_row.encrypted_api_key or env_key)
        catalog_ids = {s.model_id for s in adapter.get_default_models()}
        # Remove deprecated legacy default rows that were superseded in provider catalogs
        if adapter.provider_key in ("gemini", "anthropic"):
            for (pk, mid), m_obj in list(existing_models.items()):
                if pk == adapter.provider_key and (
                    mid.startswith(("gemini-2.5-", "gemini-2.0-", "claude-3-", "claude-sonnet-4-"))
                    and mid not in catalog_ids
                ):
                    await db.delete(m_obj)
                    existing_models.pop((pk, mid), None)

        for spec in adapter.get_default_models():
            key_pair = (spec.provider_key, spec.model_id)
            if key_pair not in existing_models:
                db.add(
                    LLMModel(
                        user_id=user.id,
                        provider_id=provider_row.id,
                        provider_key=spec.provider_key,
                        model_id=spec.model_id,
                        display_name=spec.display_name,
                        description=spec.description,
                        context_window=spec.context_window,
                        max_output_tokens=spec.max_output_tokens,
                        supports_streaming=spec.supports_streaming,
                        supports_system_instruction=spec.supports_system_instruction,
                        supports_temperature=spec.supports_temperature,
                        supports_max_tokens=spec.supports_max_tokens,
                        supports_vision=spec.supports_vision,
                        supports_file_attachments=spec.supports_file_attachments,
                        input_price_per_1m=spec.input_price_per_1m,
                        output_price_per_1m=spec.output_price_per_1m,
                        pricing_version=spec.pricing_version,
                        status="configured" if has_credentials else "unconfigured",
                        is_available=True,
                    )
                )
