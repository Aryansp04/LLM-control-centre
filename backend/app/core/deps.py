"""FastAPI authentication and rate-limiting dependencies."""

from __future__ import annotations

import uuid
from typing import Tuple

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.database import get_db
from app.models.entities import User
from app.redis_client import redis_manager

bearer_scheme = HTTPBearer(auto_error=False)


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

    if user is None or not user.is_active:
        raise AppError(
            code="unauthorized",
            message="User account not found or inactive.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

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
