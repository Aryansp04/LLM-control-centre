"""FastAPI authentication and rate-limiting dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Tuple

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import IS_VERCEL, get_settings
from app.core.errors import AppError
from app.core.security import decode_access_token, hash_password, unseal_account_cookie
from app.database import engine, get_db
from app.models.entities import LLMModel, Provider, User
from app.redis_client import redis_manager
from app.services.bootstrap import (
    ensure_user_workspace_initialized,
    get_loop_bootstrap_lock,
)

bearer_scheme = HTTPBearer(auto_error=False)
VAULT_SEAL_COOKIE = "llmcc_vault_seal"


async def get_current_user_and_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Tuple[User, dict]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            code="unauthorized",
            message="Authentication credentials were not provided.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            code="token_expired",
            message="Access token has expired. Please sign in again.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc
    except jwt.PyJWTError as exc:
        raise AppError(
            code="invalid_token",
            message="Invalid authentication token.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc

    jti = str(payload.get("jti") or "")
    if jti and await redis_manager.is_token_revoked(jti):
        raise AppError(
            code="token_revoked",
            message="Session has been logged out.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    sub = payload.get("sub")
    try:
        user_uuid = uuid.UUID(str(sub))
    except Exception as exc:
        raise AppError(
            code="invalid_token",
            message="Malformed subject in token.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc

    try:
        stmt = select(User).where(User.id == user_uuid)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
    except Exception as exc:
        raise AppError(
            code="database_unavailable",
            message="Database is temporarily unavailable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    if user is None and IS_VERCEL and engine.dialect.name == "sqlite":
        # Ephemeral `/tmp` SQLite on cold Lambda container: rehydrate verified JWT principal safely
        async with get_loop_bootstrap_lock():
            res_check = await db.execute(select(User).where(User.id == user_uuid))
            user = res_check.scalar_one_or_none()
            email_claim = str(payload.get("email") or "").lower().strip()
            if user is None and email_claim:
                base_username = str(payload.get("username") or email_claim.split("@")[0]).strip()
                rehydrated = User(
                    id=user_uuid,
                    email=email_claim,
                    username=f"{base_username[:42]}_{str(user_uuid)[:6]}" if len(base_username) < 3 else base_username[:50],
                    password_hash=hash_password(uuid.uuid4().hex),
                    full_name=payload.get("full_name"),
                    role=str(payload.get("role") or "admin"),
                    is_active=True,
                    last_login_at=datetime.now(timezone.utc),
                )
                try:
                    db.add(rehydrated)
                    await db.commit()
                    await db.refresh(rehydrated)
                    user = rehydrated
                except IntegrityError:
                    await db.rollback()
                    res_retry = await db.execute(select(User).where(User.id == user_uuid))
                    user = res_retry.scalar_one_or_none()
                    if user is None:
                        res_email = await db.execute(select(User).where(User.email == email_claim))
                        user = res_email.scalar_one_or_none()
        if user is not None:
            await ensure_user_workspace_initialized(db, user)

    if user is None or not user.is_active:
        raise AppError(
            code="unauthorized",
            message="User account not found or inactive.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # Restore user's encrypted vault keys on cold serverless containers if present in HttpOnly seal
    if IS_VERCEL and engine.dialect.name == "sqlite":
        raw_vault_cookie = request.cookies.get(VAULT_SEAL_COOKIE, "")
        if raw_vault_cookie:
            vault_payload = unseal_account_cookie(raw_vault_cookie)
            if (
                vault_payload
                and vault_payload.get("uid") == str(user.id)
                and isinstance(vault_payload.get("keys"), dict)
                and vault_payload["keys"]
            ):
                await ensure_user_workspace_initialized(db, user)
                provs = list(
                    (
                        await db.execute(
                            select(Provider).where(Provider.user_id == user.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                updated_any = False
                for p in provs:
                    enc_val = vault_payload["keys"].get(p.provider_key)
                    if enc_val and not p.encrypted_api_key:
                        p.encrypted_api_key = str(enc_val)
                        p.key_hint = "••••••••••••••••"
                        p.account_status = "verified"
                        p.status = "operational"
                        updated_any = True
                        models = list(
                            (
                                await db.execute(
                                    select(LLMModel).where(
                                        LLMModel.user_id == user.id,
                                        LLMModel.provider_id == p.id,
                                    )
                                )
                            )
                            .scalars()
                            .all()
                        )
                        for m in models:
                            if m.status == "unconfigured":
                                m.status = "configured"
                if updated_any:
                    await db.commit()

    return user, payload


async def get_current_user(
    pair: Tuple[User, dict] = Depends(get_current_user_and_token),
) -> User:
    return pair[0]


async def enforce_api_rate_limit(
    request: Request,
    user: User = Depends(get_current_user),
) -> User:
    settings = get_settings()
    allowed, remaining, retry_after = await redis_manager.check_rate_limit(
        bucket=f"api:{user.id}",
        limit=settings.rate_limit_requests_per_minute,
        window_seconds=60,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Retry in {retry_after}s.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Remaining": "0",
            },
        )
    request.state.rate_limit_remaining = remaining
    return user


async def enforce_auth_rate_limit(request: Request) -> None:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    allowed, _, retry_after = await redis_manager.check_rate_limit(
        bucket=f"auth:{client_ip}",
        limit=settings.auth_rate_limit_per_minute,
        window_seconds=60,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many authentication attempts. Retry in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )
