"""Providers & Models management API router."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import enforce_api_rate_limit
from app.core.errors import AppError
from app.core.security import encrypt_api_key, mask_api_key
from app.database import get_db
from app.models.entities import LLMModel, Provider, User
from app.providers.registry import provider_registry
from app.schemas.api_schemas import (
    ModelCreateCustomRequest,
    ModelResponse,
    ProviderResponse,
    ProviderUpdateCredentialsRequest,
)
from app.services.bootstrap import (
    ensure_user_workspace_initialized,
    resolve_provider_api_key,
)
from app.services.monitoring import run_monitoring_checks_for_user
from app.services.pricing import PRICING_CATALOG_VERSION
from app.services.quota import compute_provider_quota_status

router = APIRouter(prefix="/api", tags=["Providers & Models"])


def _serialize_provider(
    prov: Provider, model_count: int, quota: Optional[dict] = None
) -> ProviderResponse:
    api_key, source = resolve_provider_api_key(prov)
    return ProviderResponse(
        id=str(prov.id),
        provider_key=prov.provider_key,
        display_name=prov.display_name,
        has_api_key=bool(api_key),
        credential_source=source,
        key_hint=prov.key_hint if prov.encrypted_api_key else (mask_api_key(api_key) if api_key else None),
        base_url_override=prov.base_url_override,
        organization_id=prov.organization_id,
        is_enabled=prov.is_enabled,
        status=prov.status,
        account_status=prov.account_status,
        last_checked_at=prov.last_checked_at,
        last_latency_ms=prov.last_latency_ms,
        last_error=prov.last_error,
        capabilities=prov.capabilities_json or {},
        model_count=model_count,
        quota=quota,
    )


def _serialize_model(m: LLMModel, prov: Optional[Provider]) -> ModelResponse:
    has_creds = bool(prov and resolve_provider_api_key(prov)[0])
    return ModelResponse(
        id=str(m.id),
        provider_id=str(m.provider_id),
        provider_key=m.provider_key,
        provider_name=prov.display_name if prov else m.provider_key,
        model_id=m.model_id,
        display_name=m.display_name,
        description=m.description,
        context_window=m.context_window,
        max_output_tokens=m.max_output_tokens,
        supports_streaming=m.supports_streaming,
        supports_system_instruction=m.supports_system_instruction,
        supports_temperature=m.supports_temperature,
        supports_max_tokens=m.supports_max_tokens,
        supports_vision=m.supports_vision,
        supports_file_attachments=m.supports_file_attachments,
        input_price_per_1m=float(m.input_price_per_1m)
        if m.input_price_per_1m is not None
        else None,
        output_price_per_1m=float(m.output_price_per_1m)
        if m.output_price_per_1m is not None
        else None,
        pricing_version=m.pricing_version,
        status=m.status,
        provider_status=prov.status if prov else "unknown",
        account_status=prov.account_status if prov else "unconfigured",
        has_credentials=has_creds,
        is_available=m.is_available,
        last_checked_at=m.last_checked_at,
        last_latency_ms=m.last_latency_ms,
        last_error=m.last_error,
    )


@router.get("/providers", response_model=List[ProviderResponse])
async def list_providers(
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> List[ProviderResponse]:
    await ensure_user_workspace_initialized(db, user)
    providers = list(
        (
            await db.execute(
                select(Provider)
                .where(Provider.user_id == user.id)
                .order_by(Provider.provider_key.asc())
            )
        )
        .scalars()
        .all()
    )
    counts_rows = (
        await db.execute(
            select(LLMModel.provider_id, func.count(LLMModel.id))
            .where(LLMModel.user_id == user.id)
            .group_by(LLMModel.provider_id)
        )
    ).all()
    counts = {row[0]: int(row[1]) for row in counts_rows}
    out: List[ProviderResponse] = []
    for p in providers:
        q = await compute_provider_quota_status(db, user.id, p.provider_key)
        out.append(_serialize_provider(p, counts.get(p.id, 0), q))
    return out


@router.put("/providers/{provider_key}", response_model=ProviderResponse)
async def update_provider_credentials(
    provider_key: str,
    payload: ProviderUpdateCredentialsRequest,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> ProviderResponse:
    key_norm = provider_key.lower().strip()
    if not provider_registry.has(key_norm):
        raise AppError("unsupported_provider", f"Unknown provider '{provider_key}'.")

    await ensure_user_workspace_initialized(db, user)
    prov = (
        await db.execute(
            select(Provider).where(
                Provider.user_id == user.id, Provider.provider_key == key_norm
            )
        )
    ).scalar_one_or_none()
    if prov is None:
        raise AppError(
            "provider_not_found",
            f"Provider '{provider_key}' not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if payload.clear_api_key:
        prov.encrypted_api_key = None
        prov.key_hint = None
        prov.account_status = "unconfigured"
        prov.status = "unknown"
        prov.last_error = None
    elif payload.api_key is not None and payload.api_key.strip():
        clean_secret = payload.api_key.strip()
        prov.encrypted_api_key = encrypt_api_key(clean_secret)
        prov.key_hint = mask_api_key(clean_secret)
        prov.account_status = "configured"
        prov.last_error = None

    if "base_url_override" in payload.model_fields_set:
        prov.base_url_override = payload.base_url_override
    if "organization_id" in payload.model_fields_set:
        prov.organization_id = (
            payload.organization_id.strip() if payload.organization_id else None
        )
    if payload.is_enabled is not None:
        prov.is_enabled = payload.is_enabled

    # Sync associated model statuses when credentials change
    has_creds = resolve_provider_api_key(prov)[0] is not None
    models = list(
        (
            await db.execute(
                select(LLMModel).where(
                    LLMModel.user_id == user.id, LLMModel.provider_id == prov.id
                )
            )
        )
        .scalars()
        .all()
    )
    for m in models:
        if not has_creds:
            m.status = "unconfigured"
        elif m.status == "unconfigured":
            m.status = "configured"

    await db.commit()

    if payload.verify_immediately and has_creds and prov.is_enabled:
        await run_monitoring_checks_for_user(
            db, user, provider_key_filter=key_norm, deep_inference=False
        )
        await db.refresh(prov)

    q = await compute_provider_quota_status(db, user.id, prov.provider_key)
    return _serialize_provider(prov, len(models), q)


@router.get("/models", response_model=List[ModelResponse])
async def list_models(
    provider_key: Optional[str] = Query(default=None),
    available_only: bool = Query(default=False),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> List[ModelResponse]:
    await ensure_user_workspace_initialized(db, user)
    providers = {
        p.id: p
        for p in (
            await db.execute(select(Provider).where(Provider.user_id == user.id))
        )
        .scalars()
        .all()
    }

    stmt = select(LLMModel).where(LLMModel.user_id == user.id)
    if provider_key:
        stmt = stmt.where(LLMModel.provider_key == provider_key.lower())
    if available_only:
        stmt = stmt.where(LLMModel.is_available.is_(True))
    stmt = stmt.order_by(LLMModel.provider_key.asc(), LLMModel.display_name.asc())

    models = list((await db.execute(stmt)).scalars().all())
    return [_serialize_model(m, providers.get(m.provider_id)) for m in models]


@router.post(
    "/models", response_model=ModelResponse, status_code=status.HTTP_201_CREATED
)
async def register_custom_model(
    payload: ModelCreateCustomRequest,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> ModelResponse:
    pkey = payload.provider_key.lower().strip()
    if not provider_registry.has(pkey):
        raise AppError("unsupported_provider", f"Unknown provider '{pkey}'.")

    prov = (
        await db.execute(
            select(Provider).where(
                Provider.user_id == user.id, Provider.provider_key == pkey
            )
        )
    ).scalar_one_or_none()
    if prov is None:
        raise AppError("provider_not_found", f"Provider '{pkey}' not found.")

    dup = (
        await db.execute(
            select(LLMModel).where(
                LLMModel.user_id == user.id,
                LLMModel.provider_key == pkey,
                LLMModel.model_id == payload.model_id.strip(),
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise AppError(
            "model_already_exists",
            f"Model '{payload.model_id}' is already registered under {prov.display_name}.",
            status_code=status.HTTP_409_CONFLICT,
        )

    has_creds = resolve_provider_api_key(prov)[0] is not None
    new_model = LLMModel(
        user_id=user.id,
        provider_id=prov.id,
        provider_key=pkey,
        model_id=payload.model_id.strip(),
        display_name=payload.display_name.strip(),
        description=payload.description,
        context_window=payload.context_window,
        max_output_tokens=payload.max_output_tokens,
        supports_streaming=payload.supports_streaming,
        supports_system_instruction=payload.supports_system_instruction,
        supports_temperature=payload.supports_temperature,
        supports_max_tokens=payload.supports_max_tokens,
        supports_vision=payload.supports_vision,
        supports_file_attachments=payload.supports_file_attachments,
        input_price_per_1m=Decimal(str(payload.input_price_per_1m))
        if payload.input_price_per_1m is not None
        else None,
        output_price_per_1m=Decimal(str(payload.output_price_per_1m))
        if payload.output_price_per_1m is not None
        else None,
        pricing_version=PRICING_CATALOG_VERSION,
        status="configured" if has_creds else "unconfigured",
        is_available=True,
    )
    db.add(new_model)
    await db.commit()
    await db.refresh(new_model)
    return _serialize_model(new_model, prov)


@router.get("/models/{model_identifier:path}", response_model=ModelResponse)
async def get_model_detail(
    model_identifier: str,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> ModelResponse:
    m: Optional[LLMModel] = None
    try:
        m_uuid = uuid.UUID(model_identifier)
        m = (
            await db.execute(
                select(LLMModel).where(
                    LLMModel.id == m_uuid, LLMModel.user_id == user.id
                )
            )
        ).scalar_one_or_none()
    except ValueError:
        pass

    if m is None:
        m = (
            await db.execute(
                select(LLMModel).where(
                    LLMModel.model_id == model_identifier, LLMModel.user_id == user.id
                )
            )
        ).scalar_one_or_none()

    if m is None:
        raise AppError(
            "model_not_found",
            f"Model '{model_identifier}' not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    prov = await db.get(Provider, m.provider_id)
    return _serialize_model(m, prov)
