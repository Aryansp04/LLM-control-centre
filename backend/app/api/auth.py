"""Authentication API router: register, login, logout, and current user."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Tuple

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import IS_VERCEL, get_settings
from app.core.deps import (
    enforce_auth_rate_limit,
    get_current_user,
    get_current_user_and_token,
)
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    hash_password,
    needs_password_rehash,
    seal_account_cookie,
    unseal_account_cookie,
    verify_password,
)
from app.database import engine, get_db
from app.models.entities import User
from app.redis_client import redis_manager
from app.schemas.api_schemas import (
    AuthTokenResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from app.services.bootstrap import ensure_user_workspace_initialized

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

ACCOUNT_SEAL_COOKIE = "llmcc_acct_seal"


def _serialize_user(u: User) -> UserResponse:
    return UserResponse(
        id=str(u.id),
        email=u.email,
        username=u.username,
        full_name=u.full_name,
        role=u.role,
        is_active=u.is_active,
        last_login_at=u.last_login_at,
        created_at=u.created_at,
    )


def _attach_serverless_recovery_seal(response: Response, user: User) -> None:
    """Set encrypted HttpOnly account recovery cookie so Sign In survives ephemeral serverless restarts."""
    settings = get_settings()
    sealed = seal_account_cookie(
        {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
            "password_hash": user.password_hash,
        }
    )
    response.set_cookie(
        key=ACCOUNT_SEAL_COOKIE,
        value=sealed,
        max_age=30 * 24 * 3600,
        httponly=True,
        secure=IS_VERCEL or settings.is_production,
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def register_user(
    payload: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    email_norm = payload.email.lower().strip()
    username_norm = payload.username.strip()

    existing = (
        await db.execute(
            select(User).where(
                or_(User.email == email_norm, User.username == username_norm)
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.email == email_norm:
            raise AppError(
                "email_already_registered",
                "An account with this email already exists. Please sign in instead.",
                status_code=status.HTTP_409_CONFLICT,
            )
        raise AppError(
            "username_taken",
            "This username is already taken.",
            status_code=status.HTTP_409_CONFLICT,
        )

    now = datetime.now(timezone.utc)
    user = User(
        email=email_norm,
        username=username_norm,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role="admin",
        is_active=True,
        last_login_at=now,
    )
    db.add(user)
    await db.flush()

    await ensure_user_workspace_initialized(db, user, force_sync=True)
    _attach_serverless_recovery_seal(response, user)

    token, _, ttl = create_access_token(
        str(user.id),
        user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
    )
    return AuthTokenResponse(
        access_token=token,
        expires_in=ttl,
        user=_serialize_user(user),
    )


@router.post(
    "/login",
    response_model=AuthTokenResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def login_user(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    email_norm = payload.email.lower().strip()
    user = (
        await db.execute(select(User).where(User.email == email_norm))
    ).scalar_one_or_none()

    # In ephemeral serverless SQLite mode, recover previously registered operator from Fernet HttpOnly seal
    if user is None and IS_VERCEL and engine.dialect.name == "sqlite":
        sealed_cookie = request.cookies.get(ACCOUNT_SEAL_COOKIE, "")
        sealed_data = unseal_account_cookie(sealed_cookie)
        if (
            sealed_data
            and str(sealed_data.get("email") or "").lower().strip() == email_norm
            and verify_password(payload.password, str(sealed_data.get("password_hash") or ""))
        ):
            try:
                recovered_id = uuid.UUID(str(sealed_data.get("id")))
            except Exception:
                recovered_id = uuid.uuid4()
            recovered_user = User(
                id=recovered_id,
                email=email_norm,
                username=str(sealed_data.get("username") or email_norm.split("@")[0])[:50],
                password_hash=str(sealed_data["password_hash"]),
                full_name=sealed_data.get("full_name"),
                role=str(sealed_data.get("role") or "admin"),
                is_active=True,
                last_login_at=datetime.now(timezone.utc),
            )
            try:
                db.add(recovered_user)
                await db.commit()
                await db.refresh(recovered_user)
                user = recovered_user
            except IntegrityError:
                await db.rollback()
                user = (
                    await db.execute(select(User).where(User.email == email_norm))
                ).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise AppError(
            "invalid_credentials",
            "Invalid email or password. If you haven't created an account yet, switch to Create Account.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    if not user.is_active:
        raise AppError(
            "account_disabled",
            "User account is disabled.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    user.last_login_at = datetime.now(timezone.utc)
    if needs_password_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    await db.commit()

    _attach_serverless_recovery_seal(response, user)

    token, _, ttl = create_access_token(
        str(user.id),
        user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
    )
    return AuthTokenResponse(
        access_token=token,
        expires_in=ttl,
        user=_serialize_user(user),
    )


@router.post("/logout")
async def logout_user(
    pair: Tuple[User, dict] = Depends(get_current_user_and_token),
) -> dict:
    _, token_payload = pair
    jti = str(token_payload.get("jti") or "")
    exp = int(token_payload.get("exp") or 0)
    remaining_ttl = max(60, exp - int(time.time()))
    if jti:
        await redis_manager.revoke_token(jti, remaining_ttl)
    return {"status": "logged_out"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return _serialize_user(user)
