"""Real-Time Model & Provider Monitoring Engine (Modules 3 & 4).

Strictly separates:
1. Application health (Backend, PostgreSQL/DB, Redis, Streaming WS/SSE connections)
2. Provider-wide reachability (`operational`, `degraded`, `unavailable`, `unknown`)
3. API-account credential health (`unconfigured`, `configured`, `verified`, `invalid_credentials`, `rate_limited`, `quota_exceeded`)
4. Model-specific endpoint health (`unconfigured`, `configured`, `reachable`, `request_successful`, `request_failed`, `rate_limited`)
5. Individual request telemetry (Avg latency, TTFT, TPS, success/failure counts, error %, tokens, estimated cost)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import check_database_health, open_session
from app.models.entities import (
    APIRequest,
    LLMModel,
    ModelHealthCheck,
    MonitoringEvent,
    Provider,
    User,
    UserSettings,
)
from app.providers.registry import provider_registry
from app.redis_client import redis_manager
from app.services.bootstrap import resolve_provider_api_key
from app.services.events import live_event_hub

logger = logging.getLogger(__name__)

APP_STARTED_AT = time.time()


async def run_monitoring_checks_for_user(
    db: AsyncSession,
    user: User,
    *,
    provider_key_filter: Optional[str] = None,
    model_id_filter: Optional[str] = None,
    deep_inference: bool = False,
) -> Dict[str, Any]:
    """Execute live provider-specific API and model probes where credentials exist."""
    prov_stmt = select(Provider).where(Provider.user_id == user.id)
    if provider_key_filter:
        prov_stmt = prov_stmt.where(Provider.provider_key == provider_key_filter.lower())
    providers = list((await db.execute(prov_stmt)).scalars().all())

    model_stmt = select(LLMModel).where(LLMModel.user_id == user.id)
    if provider_key_filter:
        model_stmt = model_stmt.where(LLMModel.provider_key == provider_key_filter.lower())
    if model_id_filter:
        model_stmt = model_stmt.where(LLMModel.model_id == model_id_filter)
    models = list((await db.execute(model_stmt)).scalars().all())

    models_by_provider: Dict[uuid.UUID, List[LLMModel]] = {}
    for m in models:
        models_by_provider.setdefault(m.provider_id, []).append(m)

    now = datetime.now(timezone.utc)
    results_summary: List[Dict[str, Any]] = []

    for prov in providers:
        if not provider_registry.has(prov.provider_key):
            continue
        adapter = provider_registry.get(prov.provider_key)
        api_key, cred_source = resolve_provider_api_key(prov)
        prev_status = prov.status
        prov_models = models_by_provider.get(prov.id, [])

        if not api_key or not prov.is_enabled:
            prov.status = "unknown"
            prov.account_status = "unconfigured" if not api_key else "configured"
            prov.last_checked_at = now
            prov.last_error = (
                "No API key configured for this provider."
                if not api_key
                else "Provider disabled in workspace settings."
            )
            for m in prov_models:
                m.status = "unconfigured" if not api_key else "configured"
                m.last_checked_at = now
            db.add(
                ModelHealthCheck(
                    user_id=user.id,
                    provider_id=prov.id,
                    provider_key=prov.provider_key,
                    check_scope="provider_auth",
                    provider_status=prov.status,
                    account_status=prov.account_status,
                    is_healthy=False,
                    latency_ms=0.0,
                    error_message=prov.last_error,
                    details_json={"credential_source": cred_source},
                    checked_at=now,
                )
            )
            results_summary.append(
                {
                    "provider_key": prov.provider_key,
                    "provider_status": prov.status,
                    "account_status": prov.account_status,
                    "latency_ms": None,
                    "models_checked": 0,
                    "error": prov.last_error,
                }
            )
            continue

        # 1. Authenticated provider & account probe (NEVER just checking marketing homepage!)
        auth_probe = await adapter.probe_provider_and_account(
            api_key,
            base_url=prov.base_url_override,
            organization_id=prov.organization_id,
        )
        prov.status = auth_probe.provider_status
        prov.account_status = auth_probe.account_status
        prov.last_checked_at = now
        prov.last_latency_ms = auth_probe.latency_ms
        prov.last_error = auth_probe.error_message

        db.add(
            ModelHealthCheck(
                user_id=user.id,
                provider_id=prov.id,
                provider_key=prov.provider_key,
                check_scope=auth_probe.check_scope,
                provider_status=auth_probe.provider_status,
                account_status=auth_probe.account_status,
                is_healthy=auth_probe.is_healthy,
                latency_ms=auth_probe.latency_ms,
                http_status_code=auth_probe.http_status_code,
                error_message=auth_probe.error_message,
                details_json=auth_probe.details,
                checked_at=now,
            )
        )

        discovered_set = {mid.lower() for mid in auth_probe.discovered_model_ids}
        checked_models_count = 0

        # 2. Model-specific availability & optional live 1-token inference checks
        for m in prov_models:
            prev_model_status = m.status
            if not auth_probe.is_healthy:
                m.status = auth_probe.model_status or "request_failed"
                m.last_checked_at = now
                m.last_latency_ms = auth_probe.latency_ms
                m.last_error = auth_probe.error_message
                continue

            if model_id_filter or deep_inference or len(prov_models) <= 4:
                m_probe = await adapter.probe_model(
                    api_key,
                    m.model_id,
                    deep_inference=deep_inference,
                    base_url=prov.base_url_override,
                    organization_id=prov.organization_id,
                )
                checked_models_count += 1
                m.status = m_probe.model_status or (
                    "reachable" if m_probe.is_healthy else "request_failed"
                )
                m.is_available = m_probe.is_healthy
                m.last_checked_at = now
                m.last_latency_ms = m_probe.latency_ms
                m.last_error = m_probe.error_message

                db.add(
                    ModelHealthCheck(
                        user_id=user.id,
                        provider_id=prov.id,
                        model_db_id=m.id,
                        provider_key=prov.provider_key,
                        model_id=m.model_id,
                        check_scope=m_probe.check_scope,
                        provider_status=m_probe.provider_status,
                        account_status=m_probe.account_status,
                        model_status=m.status,
                        is_healthy=m_probe.is_healthy,
                        latency_ms=m_probe.latency_ms,
                        http_status_code=m_probe.http_status_code,
                        error_message=m_probe.error_message,
                        checked_at=now,
                    )
                )

                if prev_model_status != m.status:
                    await live_event_hub.emit(
                        user_id=str(user.id),
                        event_type="model_status_changed",
                        severity="info" if m_probe.is_healthy else "warning",
                        provider_key=prov.provider_key,
                        model_id=m.model_id,
                        title=f"Model {m.display_name} is {m.status.replace('_', ' ')}",
                        message=(
                            m_probe.error_message
                            or f"{m.model_id} responded in {m_probe.latency_ms} ms ({m_probe.check_scope})."
                        ),
                        payload={
                            "previous_status": prev_model_status,
                            "new_status": m.status,
                            "latency_ms": m_probe.latency_ms,
                        },
                        persist=False,
                    )
            else:
                # Verify membership in live `/models` listing returned by authenticated API
                matched = any(
                    m.model_id.lower() == d or d.startswith(m.model_id.lower())
                    for d in discovered_set
                )
                m.status = "reachable" if matched else "configured"
                m.last_checked_at = now
                m.last_latency_ms = auth_probe.latency_ms
                m.last_error = None

        await db.commit()

        if prev_status != prov.status:
            await live_event_hub.emit(
                user_id=str(user.id),
                event_type="provider_status_changed",
                severity="info" if prov.status == "operational" else "warning",
                provider_key=prov.provider_key,
                title=f"{prov.display_name} status: {prov.status}",
                message=(
                    prov.last_error
                    or f"{prov.display_name} verified ({prov.last_latency_ms} ms)."
                ),
                payload={
                    "previous_status": prev_status,
                    "new_status": prov.status,
                    "account_status": prov.account_status,
                    "latency_ms": prov.last_latency_ms,
                },
                db=db,
                persist=True,
            )

        results_summary.append(
            {
                "provider_key": prov.provider_key,
                "provider_status": prov.status,
                "account_status": prov.account_status,
                "latency_ms": prov.last_latency_ms,
                "models_checked": checked_models_count,
                "error": prov.last_error,
            }
        )

    await redis_manager.delete_cache(f"monitoring:overview:{user.id}")

    await live_event_hub.emit(
        user_id=str(user.id),
        event_type="health_check_completed",
        severity="info",
        title="Health check completed",
        message=f"Probed {len(results_summary)} provider(s).",
        payload={"results": results_summary, "deep_inference": deep_inference},
        db=db,
        persist=True,
    )

    return {"checked_at": now.isoformat(), "results": results_summary}


async def get_monitoring_overview(db: AsyncSession, user: User) -> Dict[str, Any]:
    """Compute real-time dashboard cards, system status, and performance telemetry from real records."""
    db_health, redis_health = await asyncio.gather(
        check_database_health(),
        redis_manager.check_health(),
    )
    active_generations = await redis_manager.count_active_generations(str(user.id))
    ws_connections = live_event_hub.count_connections(str(user.id))

    providers = list(
        (await db.execute(select(Provider).where(Provider.user_id == user.id)))
        .scalars()
        .all()
    )
    models = list(
        (await db.execute(select(LLMModel).where(LLMModel.user_id == user.id)))
        .scalars()
        .all()
    )

    total_providers = len(providers)
    operational_providers = sum(1 for p in providers if p.status == "operational")
    configured_providers = sum(
        1 for p in providers if resolve_provider_api_key(p)[0] is not None and p.is_enabled
    )
    available_configured_models = sum(
        1
        for m in models
        if m.is_available and m.status in ("configured", "reachable", "request_successful")
    )

    # Aggregate real API request telemetry for this user
    agg_stmt = select(
        func.count(APIRequest.id).label("total_requests"),
        func.sum(case((APIRequest.status == "success", 1), else_=0)).label("success_count"),
        func.sum(
            case((APIRequest.status.in_(["failed", "rate_limited", "timeout"]), 1), else_=0)
        ).label("failed_count"),
        func.avg(APIRequest.latency_ms).label("avg_latency_ms"),
        func.avg(APIRequest.ttft_ms).label("avg_ttft_ms"),
        func.avg(APIRequest.tokens_per_second).label("avg_tps"),
        func.coalesce(func.sum(APIRequest.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(APIRequest.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(APIRequest.total_tokens), 0).label("total_tokens"),
        func.coalesce(func.sum(APIRequest.estimated_cost_usd), Decimal("0")).label(
            "estimated_cost_usd"
        ),
    ).where(APIRequest.user_id == user.id)

    agg_row = (await db.execute(agg_stmt)).one()
    total_requests = int(agg_row.total_requests or 0)
    success_count = int(agg_row.success_count or 0)
    failed_count = int(agg_row.failed_count or 0)
    error_rate_pct = (
        round((failed_count / total_requests) * 100.0, 2) if total_requests > 0 else 0.0
    )

    provider_map = {p.id: p for p in providers}
    status_table: List[Dict[str, Any]] = []
    for m in models:
        p = provider_map.get(m.provider_id)
        has_creds = bool(p and resolve_provider_api_key(p)[0])
        status_table.append(
            {
                "model_db_id": str(m.id),
                "provider_key": m.provider_key,
                "provider_name": p.display_name if p else m.provider_key,
                "provider_status": p.status if p else "unknown",
                "account_status": p.account_status if p else "unconfigured",
                "has_credentials": has_creds,
                "model_id": m.model_id,
                "model_name": m.display_name,
                "model_status": m.status,
                "latency_ms": m.last_latency_ms
                if m.last_latency_ms is not None
                else (p.last_latency_ms if p else None),
                "last_checked_at": (
                    m.last_checked_at.isoformat()
                    if m.last_checked_at
                    else (p.last_checked_at.isoformat() if p and p.last_checked_at else None)
                ),
                "last_error": m.last_error or (p.last_error if p else None),
            }
        )

    # Recent monitoring events
    ev_stmt = (
        select(MonitoringEvent)
        .where(MonitoringEvent.user_id == user.id)
        .order_by(desc(MonitoringEvent.created_at))
        .limit(25)
    )
    events = [
        {
            "id": str(ev.id),
            "type": ev.event_type,
            "severity": ev.severity,
            "provider_key": ev.provider_key,
            "model_id": ev.model_id,
            "title": ev.title,
            "message": ev.message,
            "payload": ev.payload_json or {},
            "is_read": ev.is_read,
            "timestamp": ev.created_at.isoformat(),
        }
        for ev in (await db.execute(ev_stmt)).scalars().all()
    ]

    return {
        "cards": {
            "total_providers": total_providers,
            "configured_providers": configured_providers,
            "operational_providers": operational_providers,
            "available_models": available_configured_models,
            "total_models": len(models),
            "active_generations": active_generations,
            "total_requests": total_requests,
            "successful_requests": success_count,
            "failed_requests": failed_count,
            "avg_latency_ms": round(float(agg_row.avg_latency_ms), 2)
            if agg_row.avg_latency_ms is not None
            else None,
            "avg_ttft_ms": round(float(agg_row.avg_ttft_ms), 2)
            if agg_row.avg_ttft_ms is not None
            else None,
            "avg_tokens_per_second": round(float(agg_row.avg_tps), 2)
            if agg_row.avg_tps is not None
            else None,
            "input_tokens": int(agg_row.input_tokens or 0),
            "output_tokens": int(agg_row.output_tokens or 0),
            "total_tokens": int(agg_row.total_tokens or 0),
            "error_rate_pct": error_rate_pct,
            "estimated_cost_usd": round(float(agg_row.estimated_cost_usd or 0), 6),
        },
        "application_status": {
            "backend": {
                "status": "operational",
                "healthy": True,
                "uptime_seconds": int(time.time() - APP_STARTED_AT),
            },
            "database": db_health,
            "redis": redis_health,
            "streaming": {
                "status": "operational",
                "healthy": True,
                "active_websocket_connections": ws_connections,
                "active_sse_generations": active_generations,
            },
        },
        "provider_status_table": status_table,
        "recent_events": events,
    }


async def background_monitoring_loop(stop_event: asyncio.Event) -> None:
    """Periodic background health monitor coordinated via Redis lock."""
    settings = get_settings()
    interval = max(30, settings.background_monitoring_interval_seconds)

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass

        lock_token = await redis_manager.acquire_job_lock(
            "periodic_health_monitor", ttl_seconds=min(interval - 5, 120)
        )
        if not lock_token:
            continue

        try:
            async with open_session() as db:
                users_stmt = (
                    select(User)
                    .join(UserSettings, UserSettings.user_id == User.id)
                    .where(
                        User.is_active.is_(True),
                        UserSettings.auto_monitoring_enabled.is_(True),
                    )
                )
                users = list((await db.execute(users_stmt)).scalars().all())
                for u in users:
                    uset = (
                        await db.execute(
                            select(UserSettings).where(UserSettings.user_id == u.id)
                        )
                    ).scalar_one_or_none()
                    await run_monitoring_checks_for_user(
                        db,
                        u,
                        deep_inference=bool(uset and uset.enable_deep_model_probe),
                    )
        except Exception as exc:
            logger.warning("Background monitoring cycle error: %s", type(exc).__name__)
        finally:
            await redis_manager.release_job_lock("periodic_health_monitor", lock_token)
