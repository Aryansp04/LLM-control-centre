"""Real-Time Monitoring REST Endpoints & Authenticated WebSocket Server."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import case, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import enforce_api_rate_limit
from app.core.security import decode_access_token
from app.database import get_db, open_session
from app.models.entities import (
    APIRequest,
    LLMModel,
    ModelHealthCheck,
    MonitoringEvent,
    Provider,
    User,
)
from app.redis_client import redis_manager
from app.schemas.api_schemas import MonitoringCheckRequest
from app.services.bootstrap import (
    ensure_user_workspace_initialized,
    resolve_provider_api_key,
)
from app.services.events import live_event_hub
from app.services.monitoring import (
    get_monitoring_overview,
    run_monitoring_checks_for_user,
)

router = APIRouter(tags=["Monitoring & Live Events"])


@router.get("/api/monitoring/overview")
async def monitoring_overview_endpoint(
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    await ensure_user_workspace_initialized(db, user)
    cache_key = f"monitoring:overview:{user.id}"
    cached = await redis_manager.get_json(cache_key)
    if cached:
        # Refresh dynamic in-memory socket & active stream counters even on short cache hit
        cached["cards"]["active_generations"] = await redis_manager.count_active_generations(
            str(user.id)
        )
        cached["application_status"]["streaming"]["active_websocket_connections"] = (
            live_event_hub.count_connections(str(user.id))
        )
        return cached

    data = await get_monitoring_overview(db, user)
    await redis_manager.set_json(cache_key, data, ttl_seconds=6)
    return data


@router.get("/api/monitoring/providers")
async def monitoring_providers_endpoint(
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
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

    stats_rows = (
        await db.execute(
            select(
                APIRequest.provider_key,
                func.count(APIRequest.id).label("requests"),
                func.sum(case((APIRequest.status == "success", 1), else_=0)).label("success"),
                func.sum(
                    case(
                        (APIRequest.status.in_(["failed", "rate_limited", "timeout"]), 1),
                        else_=0,
                    )
                ).label("failed"),
                func.avg(APIRequest.latency_ms).label("avg_latency"),
                func.avg(APIRequest.ttft_ms).label("avg_ttft"),
            )
            .where(APIRequest.user_id == user.id)
            .group_by(APIRequest.provider_key)
        )
    ).all()
    stats_map = {r.provider_key: r for r in stats_rows}

    out = []
    for p in providers:
        st = stats_map.get(p.provider_key)
        req_total = int(st.requests or 0) if st else 0
        failed_total = int(st.failed or 0) if st else 0
        api_key, cred_source = resolve_provider_api_key(p)
        out.append(
            {
                "id": str(p.id),
                "provider_key": p.provider_key,
                "display_name": p.display_name,
                "is_enabled": p.is_enabled,
                "has_credentials": bool(api_key),
                "credential_source": cred_source,
                "provider_status": p.status,
                "account_status": p.account_status,
                "last_checked_at": p.last_checked_at.isoformat()
                if p.last_checked_at
                else None,
                "last_probe_latency_ms": p.last_latency_ms,
                "last_error": p.last_error,
                "request_count": req_total,
                "successful_requests": int(st.success or 0) if st else 0,
                "failed_requests": failed_total,
                "error_rate_pct": round((failed_total / req_total) * 100.0, 2)
                if req_total > 0
                else 0.0,
                "avg_request_latency_ms": round(float(st.avg_latency), 2)
                if st and st.avg_latency is not None
                else None,
                "avg_ttft_ms": round(float(st.avg_ttft), 2)
                if st and st.avg_ttft is not None
                else None,
            }
        )
    return {"providers": out}


@router.get("/api/monitoring/models")
async def monitoring_models_endpoint(
    provider_key: Optional[str] = Query(default=None),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    await ensure_user_workspace_initialized(db, user)
    prov_map = {
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
    models = list(
        (await db.execute(stmt.order_by(LLMModel.provider_key, LLMModel.model_id)))
        .scalars()
        .all()
    )

    stats_rows = (
        await db.execute(
            select(
                APIRequest.provider_key,
                APIRequest.requested_model,
                func.count(APIRequest.id).label("requests"),
                func.sum(case((APIRequest.status == "success", 1), else_=0)).label("success"),
                func.sum(
                    case(
                        (APIRequest.status.in_(["failed", "rate_limited", "timeout"]), 1),
                        else_=0,
                    )
                ).label("failed"),
                func.avg(APIRequest.latency_ms).label("avg_latency"),
                func.avg(APIRequest.ttft_ms).label("avg_ttft"),
                func.avg(APIRequest.tokens_per_second).label("avg_tps"),
                func.coalesce(func.sum(APIRequest.total_tokens), 0).label("tokens"),
            )
            .where(APIRequest.user_id == user.id)
            .group_by(APIRequest.provider_key, APIRequest.requested_model)
        )
    ).all()
    stats_map = {(r.provider_key, r.requested_model): r for r in stats_rows}

    out = []
    for m in models:
        p = prov_map.get(m.provider_id)
        st = stats_map.get((m.provider_key, m.model_id))
        req_total = int(st.requests or 0) if st else 0
        failed_total = int(st.failed or 0) if st else 0
        out.append(
            {
                "id": str(m.id),
                "provider_key": m.provider_key,
                "provider_name": p.display_name if p else m.provider_key,
                "provider_status": p.status if p else "unknown",
                "account_status": p.account_status if p else "unconfigured",
                "model_id": m.model_id,
                "display_name": m.display_name,
                "model_status": m.status,
                "is_available": m.is_available,
                "last_checked_at": m.last_checked_at.isoformat()
                if m.last_checked_at
                else None,
                "probe_latency_ms": m.last_latency_ms,
                "last_error": m.last_error,
                "request_count": req_total,
                "successful_requests": int(st.success or 0) if st else 0,
                "failed_requests": failed_total,
                "error_rate_pct": round((failed_total / req_total) * 100.0, 2)
                if req_total > 0
                else 0.0,
                "avg_latency_ms": round(float(st.avg_latency), 2)
                if st and st.avg_latency is not None
                else None,
                "avg_ttft_ms": round(float(st.avg_ttft), 2)
                if st and st.avg_ttft is not None
                else None,
                "avg_tokens_per_second": round(float(st.avg_tps), 2)
                if st and st.avg_tps is not None
                else None,
                "total_tokens": int(st.tokens or 0) if st else 0,
            }
        )
    return {"models": out}


@router.get("/api/monitoring/history")
async def monitoring_history_endpoint(
    provider_key: Optional[str] = Query(default=None),
    model_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    stmt = select(ModelHealthCheck).where(ModelHealthCheck.user_id == user.id)
    if provider_key:
        stmt = stmt.where(ModelHealthCheck.provider_key == provider_key.lower())
    if model_id:
        stmt = stmt.where(ModelHealthCheck.model_id == model_id)
    stmt = stmt.order_by(desc(ModelHealthCheck.checked_at)).limit(limit)

    checks = list((await db.execute(stmt)).scalars().all())
    return {
        "items": [
            {
                "id": str(c.id),
                "provider_key": c.provider_key,
                "model_id": c.model_id,
                "check_scope": c.check_scope,
                "provider_status": c.provider_status,
                "account_status": c.account_status,
                "model_status": c.model_status,
                "is_healthy": c.is_healthy,
                "latency_ms": c.latency_ms,
                "http_status_code": c.http_status_code,
                "error_message": c.error_message,
                "checked_at": c.checked_at.isoformat(),
            }
            for c in checks
        ]
    }


@router.post("/api/monitoring/check")
async def trigger_monitoring_check(
    payload: MonitoringCheckRequest,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    await ensure_user_workspace_initialized(db, user)
    return await run_monitoring_checks_for_user(
        db,
        user,
        provider_key_filter=payload.provider_key,
        model_id_filter=payload.model_id,
        deep_inference=payload.deep_inference,
    )


@router.post("/api/monitoring/events/read-all")
async def mark_monitoring_events_read(
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    await db.execute(
        update(MonitoringEvent)
        .where(MonitoringEvent.user_id == user.id, MonitoringEvent.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()
    await redis_manager.delete_cache(f"monitoring:overview:{user.id}")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Authenticated Live WebSocket Endpoint (/ws/events)
# ---------------------------------------------------------------------------
async def _authenticate_websocket(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        jti = str(payload.get("jti") or "")
        if jti and await redis_manager.is_token_revoked(jti):
            return None
        sub = str(payload.get("sub") or "")
        user_uuid = uuid.UUID(sub)
        async with open_session() as db:
            user = await db.get(User, user_uuid)
            if user is None or not user.is_active:
                return None
            return str(user.id)
    except Exception:
        return None


@router.websocket("/ws/events")
async def websocket_live_events(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
    last_seq: int = Query(default=0, ge=0),
) -> None:
    # Support token via query param OR Authorization bearer header
    auth_header = websocket.headers.get("authorization", "")
    bearer_tok = (
        auth_header[7:].strip()
        if auth_header.lower().startswith("bearer ")
        else None
    )
    user_id = await _authenticate_websocket(bearer_tok or token)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await live_event_hub.connect(user_id, websocket, last_seq=last_seq)

    async def _heartbeat_sender() -> None:
        while True:
            await asyncio.sleep(20)
            await live_event_hub.send_heartbeat(user_id, websocket)

    hb_task = asyncio.create_task(_heartbeat_sender())
    try:
        while True:
            raw_msg = await websocket.receive_text()
            try:
                data = json.loads(raw_msg)
            except Exception:
                continue
            if data.get("type") == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "client_ts": data.get("ts"),
                    }
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hb_task.cancel()
        await live_event_hub.disconnect(user_id, websocket)
