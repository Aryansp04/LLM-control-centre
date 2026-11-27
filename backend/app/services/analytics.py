"""Analytics & Usage Tracking Service (Module 6).

Computes real telemetry time-series (daily, weekly, monthly, hourly), provider/model
breakdowns, latency/TTFT distributions, error rates, and versioned cost estimates
directly from PostgreSQL/SQLAlchemy `APIRequest` and `UsageRecord` rows.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import APIRequest, User
from app.services.pricing import PRICING_CATALOG_VERSION


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bucket_key(dt: datetime, granularity: str) -> str:
    utc_dt = _ensure_utc(dt)
    if granularity == "hourly":
        return utc_dt.strftime("%Y-%m-%d %H:00")
    if granularity == "weekly":
        iso_year, iso_week, _ = utc_dt.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "monthly":
        return utc_dt.strftime("%Y-%m")
    return utc_dt.strftime("%Y-%m-%d")


async def query_filtered_requests(
    db: AsyncSession,
    user: User,
    *,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    provider_key: Optional[str] = None,
    model_id: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> List[APIRequest]:
    stmt = select(APIRequest).where(APIRequest.user_id == user.id)
    if start_date:
        stmt = stmt.where(APIRequest.created_at >= _ensure_utc(start_date))
    if end_date:
        stmt = stmt.where(APIRequest.created_at <= _ensure_utc(end_date))
    if provider_key:
        stmt = stmt.where(APIRequest.provider_key == provider_key.lower())
    if model_id:
        stmt = stmt.where(APIRequest.requested_model == model_id)
    if status_filter:
        stmt = stmt.where(APIRequest.status == status_filter.lower())
    stmt = stmt.order_by(APIRequest.created_at.asc())
    return list((await db.execute(stmt)).scalars().all())


async def build_comprehensive_analytics(
    db: AsyncSession,
    user: User,
    *,
    granularity: str = "daily",
    days: int = 30,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    provider_key: Optional[str] = None,
    model_id: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    effective_start = start_date or (now - timedelta(days=max(1, days)))
    effective_end = end_date or now

    rows = await query_filtered_requests(
        db,
        user,
        start_date=effective_start,
        end_date=effective_end,
        provider_key=provider_key,
        model_id=model_id,
        status_filter=status_filter,
    )

    total_requests = len(rows)
    success_requests = 0
    failed_requests = 0
    cancelled_requests = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost_usd = 0.0
    priced_requests = 0
    unpriced_requests = 0
    latencies: List[float] = []
    ttfts: List[float] = []
    tps_values: List[float] = []

    buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "bucket": "",
            "requests": 0,
            "successful": 0,
            "failed": 0,
            "cancelled": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_sum": 0.0,
            "latency_count": 0,
            "ttft_sum": 0.0,
            "ttft_count": 0,
            "estimated_cost_usd": 0.0,
        }
    )

    by_provider: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "provider_key": "",
            "requests": 0,
            "successful": 0,
            "failed": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_sum": 0.0,
            "estimated_cost_usd": 0.0,
        }
    )

    by_model: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "provider_key": "",
            "model_id": "",
            "requests": 0,
            "successful": 0,
            "failed": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_sum": 0.0,
            "ttft_sum": 0.0,
            "ttft_count": 0,
            "tps_sum": 0.0,
            "tps_count": 0,
            "estimated_cost_usd": 0.0,
            "pricing_version": PRICING_CATALOG_VERSION,
        }
    )

    # Also compute explicit daily / weekly / monthly window summaries
    day_cutoff = now - timedelta(days=1)
    week_cutoff = now - timedelta(days=7)
    month_cutoff = now - timedelta(days=30)
    period_windows = {
        "daily": {"requests": 0, "tokens": 0, "estimated_cost_usd": 0.0, "failed": 0},
        "weekly": {"requests": 0, "tokens": 0, "estimated_cost_usd": 0.0, "failed": 0},
        "monthly": {"requests": 0, "tokens": 0, "estimated_cost_usd": 0.0, "failed": 0},
    }

    for r in rows:
        created_utc = _ensure_utc(r.created_at)
        is_success = r.status == "success"
        is_cancelled = r.status == "cancelled"
        is_failed = r.status in ("failed", "rate_limited", "timeout")

        if is_success:
            success_requests += 1
        elif is_cancelled:
            cancelled_requests += 1
        elif is_failed:
            failed_requests += 1

        total_input_tokens += r.input_tokens
        total_output_tokens += r.output_tokens
        latencies.append(r.latency_ms)
        if r.ttft_ms is not None:
            ttfts.append(r.ttft_ms)
        if r.tokens_per_second is not None:
            tps_values.append(r.tokens_per_second)

        cost_val = float(r.estimated_cost_usd) if r.estimated_cost_usd is not None else 0.0
        if r.estimated_cost_usd is not None:
            total_cost_usd += cost_val
            priced_requests += 1
        else:
            unpriced_requests += 1

        for window_name, cutoff in (
            ("daily", day_cutoff),
            ("weekly", week_cutoff),
            ("monthly", month_cutoff),
        ):
            if created_utc >= cutoff:
                period_windows[window_name]["requests"] += 1
                period_windows[window_name]["tokens"] += r.total_tokens
                period_windows[window_name]["estimated_cost_usd"] += cost_val
                if is_failed:
                    period_windows[window_name]["failed"] += 1

        bkey = _bucket_key(created_utc, granularity)
        b = buckets[bkey]
        b["bucket"] = bkey
        b["requests"] += 1
        b["successful"] += 1 if is_success else 0
        b["failed"] += 1 if is_failed else 0
        b["cancelled"] += 1 if is_cancelled else 0
        b["input_tokens"] += r.input_tokens
        b["output_tokens"] += r.output_tokens
        b["total_tokens"] += r.total_tokens
        b["latency_sum"] += r.latency_ms
        b["latency_count"] += 1
        if r.ttft_ms is not None:
            b["ttft_sum"] += r.ttft_ms
            b["ttft_count"] += 1
        b["estimated_cost_usd"] += cost_val

        p = by_provider[r.provider_key]
        p["provider_key"] = r.provider_key
        p["requests"] += 1
        p["successful"] += 1 if is_success else 0
        p["failed"] += 1 if is_failed else 0
        p["input_tokens"] += r.input_tokens
        p["output_tokens"] += r.output_tokens
        p["total_tokens"] += r.total_tokens
        p["latency_sum"] += r.latency_ms
        p["estimated_cost_usd"] += cost_val

        m_label = f"{r.provider_key}:{r.requested_model}"
        m = by_model[m_label]
        m["provider_key"] = r.provider_key
        m["model_id"] = r.requested_model
        m["requests"] += 1
        m["successful"] += 1 if is_success else 0
        m["failed"] += 1 if is_failed else 0
        m["input_tokens"] += r.input_tokens
        m["output_tokens"] += r.output_tokens
        m["total_tokens"] += r.total_tokens
        m["latency_sum"] += r.latency_ms
        if r.ttft_ms is not None:
            m["ttft_sum"] += r.ttft_ms
            m["ttft_count"] += 1
        if r.tokens_per_second is not None:
            m["tps_sum"] += r.tokens_per_second
            m["tps_count"] += 1
        m["estimated_cost_usd"] += cost_val
        if r.pricing_version:
            m["pricing_version"] = r.pricing_version

    timeseries: List[Dict[str, Any]] = []
    for k in sorted(buckets.keys()):
        item = buckets[k]
        cnt = item["latency_count"] or 1
        t_cnt = item["ttft_count"]
        timeseries.append(
            {
                "bucket": item["bucket"],
                "requests": item["requests"],
                "successful": item["successful"],
                "failed": item["failed"],
                "cancelled": item["cancelled"],
                "input_tokens": item["input_tokens"],
                "output_tokens": item["output_tokens"],
                "total_tokens": item["total_tokens"],
                "avg_latency_ms": round(item["latency_sum"] / cnt, 2),
                "avg_ttft_ms": round(item["ttft_sum"] / t_cnt, 2) if t_cnt else None,
                "estimated_cost_usd": round(item["estimated_cost_usd"], 6),
            }
        )

    provider_breakdown: List[Dict[str, Any]] = []
    for k, item in sorted(by_provider.items(), key=lambda kv: kv[1]["requests"], reverse=True):
        cnt = item["requests"] or 1
        provider_breakdown.append(
            {
                "provider_key": k,
                "requests": item["requests"],
                "successful": item["successful"],
                "failed": item["failed"],
                "failure_rate_pct": round((item["failed"] / cnt) * 100.0, 2),
                "input_tokens": item["input_tokens"],
                "output_tokens": item["output_tokens"],
                "total_tokens": item["total_tokens"],
                "avg_latency_ms": round(item["latency_sum"] / cnt, 2),
                "estimated_cost_usd": round(item["estimated_cost_usd"], 6),
            }
        )

    model_breakdown: List[Dict[str, Any]] = []
    for _, item in sorted(by_model.items(), key=lambda kv: kv[1]["requests"], reverse=True):
        cnt = item["requests"] or 1
        model_breakdown.append(
            {
                "provider_key": item["provider_key"],
                "model_id": item["model_id"],
                "requests": item["requests"],
                "successful": item["successful"],
                "failed": item["failed"],
                "failure_rate_pct": round((item["failed"] / cnt) * 100.0, 2),
                "input_tokens": item["input_tokens"],
                "output_tokens": item["output_tokens"],
                "total_tokens": item["total_tokens"],
                "avg_latency_ms": round(item["latency_sum"] / cnt, 2),
                "avg_ttft_ms": (
                    round(item["ttft_sum"] / item["ttft_count"], 2)
                    if item["ttft_count"]
                    else None
                ),
                "avg_tokens_per_second": (
                    round(item["tps_sum"] / item["tps_count"], 2)
                    if item["tps_count"]
                    else None
                ),
                "estimated_cost_usd": round(item["estimated_cost_usd"], 6),
                "pricing_version": item["pricing_version"],
            }
        )

    sorted_lat = sorted(latencies)
    p95_latency = (
        round(sorted_lat[min(len(sorted_lat) - 1, int(len(sorted_lat) * 0.95))], 2)
        if sorted_lat
        else None
    )

    for w in period_windows.values():
        w["estimated_cost_usd"] = round(w["estimated_cost_usd"], 6)

    return {
        "summary": {
            "total_requests": total_requests,
            "successful_requests": success_requests,
            "failed_requests": failed_requests,
            "cancelled_requests": cancelled_requests,
            "failure_rate_pct": (
                round((failed_requests / total_requests) * 100.0, 2)
                if total_requests > 0
                else 0.0
            ),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "avg_latency_ms": (
                round(sum(latencies) / len(latencies), 2) if latencies else None
            ),
            "p95_latency_ms": p95_latency,
            "avg_ttft_ms": round(sum(ttfts) / len(ttfts), 2) if ttfts else None,
            "avg_tokens_per_second": (
                round(sum(tps_values) / len(tps_values), 2) if tps_values else None
            ),
            "estimated_cost_usd": round(total_cost_usd, 6),
            "is_cost_estimated": True,
            "pricing_version": PRICING_CATALOG_VERSION,
            "priced_requests": priced_requests,
            "unpriced_requests": unpriced_requests,
        },
        "periods": period_windows,
        "timeseries": timeseries,
        "by_provider": provider_breakdown,
        "by_model": model_breakdown,
        "filters_applied": {
            "granularity": granularity,
            "start_date": effective_start.isoformat(),
            "end_date": effective_end.isoformat(),
            "provider_key": provider_key,
            "model_id": model_id,
            "status": status_filter,
        },
    }


async def list_api_request_logs(
    db: AsyncSession,
    user: User,
    *,
    page: int = 1,
    page_size: int = 30,
    provider_key: Optional[str] = None,
    model_id: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> Dict[str, Any]:
    stmt = select(APIRequest).where(APIRequest.user_id == user.id)
    if provider_key:
        stmt = stmt.where(APIRequest.provider_key == provider_key.lower())
    if model_id:
        stmt = stmt.where(APIRequest.requested_model == model_id)
    if status_filter:
        stmt = stmt.where(APIRequest.status == status_filter.lower())

    all_matching = list(
        (await db.execute(stmt.order_by(desc(APIRequest.created_at)))).scalars().all()
    )
    total = len(all_matching)
    offset = max(0, (page - 1) * page_size)
    sliced = all_matching[offset : offset + page_size]

    return {
        "items": [
            {
                "id": str(r.id),
                "request_id": r.request_id,
                "conversation_id": str(r.conversation_id) if r.conversation_id else None,
                "provider_key": r.provider_key,
                "requested_model": r.requested_model,
                "actual_model_used": r.actual_model_used,
                "endpoint_type": r.endpoint_type,
                "is_streaming": r.is_streaming,
                "status": r.status,
                "http_status_code": r.http_status_code,
                "error_type": r.error_type,
                "error_message": r.error_message,
                "retry_count": r.retry_count,
                "latency_ms": r.latency_ms,
                "ttft_ms": r.ttft_ms,
                "tokens_per_second": r.tokens_per_second,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "estimated_cost_usd": float(r.estimated_cost_usd)
                if r.estimated_cost_usd is not None
                else None,
                "pricing_version": r.pricing_version,
                "created_at": r.created_at.isoformat(),
            }
            for r in sliced
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }
