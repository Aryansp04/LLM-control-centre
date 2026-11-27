"""Rolling Multi-Hour Usage Quota Tracker for OpenAI, Gemini, and Anthropic.

Tracks real token consumption within a rolling window (default: 4 hours) per user and
provider. Usage starts at 100% available and automatically recovers back to 100% as
requests age past the 4-hour reset window.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.entities import APIRequest

QUOTA_RESET_WINDOW_HOURS = 4
DEFAULT_WINDOW_TOKEN_BUDGET: Dict[str, int] = {
    "openai": 100_000,
    "gemini": 150_000,
    "anthropic": 100_000,
}


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def compute_provider_quota_status(
    db: AsyncSession,
    user_id: uuid.UUID,
    provider_key: str,
    *,
    window_hours: int = QUOTA_RESET_WINDOW_HOURS,
    now_override: datetime | None = None,
) -> Dict[str, Any]:
    """Compute real remaining percentage (0–100%) and reset countdown for `provider_key`."""
    now = _ensure_utc(now_override or datetime.now(timezone.utc))
    window_delta = timedelta(hours=window_hours)
    cutoff = now - window_delta
    pkey = provider_key.lower().strip()
    token_limit = DEFAULT_WINDOW_TOKEN_BUDGET.get(pkey, 100_000)

    stmt = (
        select(APIRequest.total_tokens, APIRequest.created_at)
        .where(
            APIRequest.user_id == user_id,
            APIRequest.provider_key == pkey,
            APIRequest.created_at >= cutoff,
            APIRequest.total_tokens > 0,
        )
        .order_by(APIRequest.created_at.asc())
    )
    rows = (await db.execute(stmt)).all()

    used_tokens = sum(int(r[0] or 0) for r in rows)
    used_ratio = min(1.0, used_tokens / float(token_limit)) if token_limit > 0 else 0.0
    remaining_pct = round(max(0.0, (1.0 - used_ratio) * 100.0), 1)
    used_pct = round(min(100.0, used_ratio * 100.0), 1)

    if rows:
        oldest_ts = _ensure_utc(rows[0][1])
        next_recovery_at = oldest_ts + window_delta
        full_reset_at = _ensure_utc(rows[-1][1]) + window_delta
    else:
        next_recovery_at = now + window_delta
        full_reset_at = now + window_delta

    reset_in_seconds = max(0, int((full_reset_at - now).total_seconds()))

    return {
        "window_hours": window_hours,
        "token_limit": token_limit,
        "used_tokens": used_tokens,
        "remaining_tokens": max(0, token_limit - used_tokens),
        "remaining_pct": remaining_pct,
        "used_pct": used_pct,
        "next_recovery_at": next_recovery_at.isoformat(),
        "resets_to_100_at": full_reset_at.isoformat(),
        "reset_in_seconds": reset_in_seconds,
    }


async def enforce_provider_window_quota(
    db: AsyncSession,
    user_id: uuid.UUID,
    provider_key: str,
) -> Dict[str, Any]:
    quota = await compute_provider_quota_status(db, user_id, provider_key)
    if quota["remaining_tokens"] <= 0:
        mins = max(1, quota["reset_in_seconds"] // 60)
        raise AppError(
            code="window_quota_exhausted",
            message=(
                f"{provider_key.upper()} 4-hour usage allowance reached (0% remaining). "
                f"Usage resets back to 100% in ~{mins} min."
            ),
            status_code=429,
            details=quota,
        )
    return quota
