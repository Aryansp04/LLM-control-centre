"""Analytics, Usage Tracking, API Logs, User Settings, and Health Endpoints."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import enforce_api_rate_limit
from app.database import check_database_health, get_db
from app.models.entities import User, UserSettings
from app.redis_client import redis_manager
from app.schemas.api_schemas import UserSettingsUpdateRequest
from app.services.analytics import (
    build_comprehensive_analytics,
    list_api_request_logs,
)
from app.services.bootstrap import ensure_user_workspace_initialized
from app.services.monitoring import APP_STARTED_AT

router = APIRouter(tags=["Analytics, Logs, Settings & Health"])


# ---------------------------------------------------------------------------
# Analytics Endpoints
# ---------------------------------------------------------------------------
@router.get("/api/analytics/usage")
async def analytics_usage_endpoint(
    granularity: str = Query(default="daily", pattern="^(hourly|daily|weekly|monthly)$"),
    days: int = Query(default=30, ge=1, le=365),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await build_comprehensive_analytics(
        db,
        user,
        granularity=granularity,
        days=days,
        start_date=start_date,
        end_date=end_date,
        provider_key=provider,
        model_id=model,
        status_filter=status_filter,
    )


@router.get("/api/analytics/tokens")
async def analytics_tokens_endpoint(
    granularity: str = Query(default="daily", pattern="^(hourly|daily|weekly|monthly)$"),
    days: int = Query(default=30, ge=1, le=365),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    report = await build_comprehensive_analytics(
        db,
        user,
        granularity=granularity,
        days=days,
        start_date=start_date,
        end_date=end_date,
        provider_key=provider,
        model_id=model,
        status_filter=status_filter,
    )
    return {
        "input_tokens": report["summary"]["input_tokens"],
        "output_tokens": report["summary"]["output_tokens"],
        "total_tokens": report["summary"]["total_tokens"],
        "timeseries": [
            {
                "bucket": b["bucket"],
                "input_tokens": b["input_tokens"],
                "output_tokens": b["output_tokens"],
                "total_tokens": b["total_tokens"],
            }
            for b in report["timeseries"]
        ],
        "by_provider": report["by_provider"],
        "by_model": report["by_model"],
    }


@router.get("/api/analytics/latency")
async def analytics_latency_endpoint(
    granularity: str = Query(default="daily", pattern="^(hourly|daily|weekly|monthly)$"),
    days: int = Query(default=30, ge=1, le=365),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    report = await build_comprehensive_analytics(
        db,
        user,
        granularity=granularity,
        days=days,
        start_date=start_date,
        end_date=end_date,
        provider_key=provider,
        model_id=model,
        status_filter=status_filter,
    )
    return {
        "avg_latency_ms": report["summary"]["avg_latency_ms"],
        "p95_latency_ms": report["summary"]["p95_latency_ms"],
        "avg_ttft_ms": report["summary"]["avg_ttft_ms"],
        "avg_tokens_per_second": report["summary"]["avg_tokens_per_second"],
        "timeseries": [
            {
                "bucket": b["bucket"],
                "avg_latency_ms": b["avg_latency_ms"],
                "avg_ttft_ms": b["avg_ttft_ms"],
                "requests": b["requests"],
            }
            for b in report["timeseries"]
        ],
        "by_model": report["by_model"],
    }


@router.get("/api/analytics/cost")
async def analytics_cost_endpoint(
    granularity: str = Query(default="daily", pattern="^(hourly|daily|weekly|monthly)$"),
    days: int = Query(default=30, ge=1, le=365),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    report = await build_comprehensive_analytics(
        db,
        user,
        granularity=granularity,
        days=days,
        start_date=start_date,
        end_date=end_date,
        provider_key=provider,
        model_id=model,
        status_filter=status_filter,
    )
    return {
        "estimated_cost_usd": report["summary"]["estimated_cost_usd"],
        "is_cost_estimated": True,
        "cost_disclaimer": (
            "All costs are estimates calculated from recorded input/output token counts "
            "and versioned provider list pricing. Actual provider invoices may vary."
        ),
        "pricing_version": report["summary"]["pricing_version"],
        "priced_requests": report["summary"]["priced_requests"],
        "unpriced_requests": report["summary"]["unpriced_requests"],
        "periods": report["periods"],
        "timeseries": [
            {
                "bucket": b["bucket"],
                "estimated_cost_usd": b["estimated_cost_usd"],
                "total_tokens": b["total_tokens"],
            }
            for b in report["timeseries"]
        ],
        "by_provider": report["by_provider"],
        "by_model": report["by_model"],
    }


# ---------------------------------------------------------------------------
# API Request Logs Endpoint
# ---------------------------------------------------------------------------
@router.get("/api/logs")
async def get_api_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await list_api_request_logs(
        db,
        user,
        page=page,
        page_size=page_size,
        provider_key=provider,
        model_id=model,
        status_filter=status_filter,
    )


# ---------------------------------------------------------------------------
# User Workspace Settings Endpoints
# ---------------------------------------------------------------------------
@router.get("/api/settings")
async def get_user_settings_endpoint(
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    await ensure_user_workspace_initialized(db, user)
    s = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    ).scalar_one()
    return {
        "workspace_name": s.workspace_name,
        "default_provider": s.default_provider,
        "default_model": s.default_model,
        "default_temperature": s.default_temperature,
        "default_max_tokens": s.default_max_tokens,
        "default_system_instruction": s.default_system_instruction,
        "context_max_tokens_ratio": s.context_max_tokens_ratio,
        "auto_monitoring_enabled": s.auto_monitoring_enabled,
        "monitoring_interval_seconds": s.monitoring_interval_seconds,
        "enable_deep_model_probe": s.enable_deep_model_probe,
        "notifications_enabled": s.notifications_enabled,
        "updated_at": s.updated_at.isoformat(),
    }


@router.put("/api/settings")
async def update_user_settings_endpoint(
    payload: UserSettingsUpdateRequest,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    await ensure_user_workspace_initialized(db, user)
    s = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    ).scalar_one()

    for field_name in payload.model_fields_set:
        val = getattr(payload, field_name)
        if val is not None or field_name == "default_system_instruction":
            setattr(s, field_name, val)

    await db.commit()
    await db.refresh(s)
    return await get_user_settings_endpoint(user=user, db=db)


# ---------------------------------------------------------------------------
# Health & Readiness Probes (/health and /ready)
# ---------------------------------------------------------------------------
@router.get("/health")
async def liveness_health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "llm-control-center-backend",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - APP_STARTED_AT),
    }


@router.get("/ready")
async def readiness_health() -> JSONResponse:
    db_health, redis_health = await asyncio.gather(
        check_database_health(),
        redis_manager.check_health(),
    )
    overall_ready = bool(db_health["healthy"] and redis_health["healthy"])
    code = status.HTTP_200_OK if overall_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=code,
        content={
            "status": "ready" if overall_ready else "degraded",
            "database": db_health,
            "redis": redis_health,
        },
    )
