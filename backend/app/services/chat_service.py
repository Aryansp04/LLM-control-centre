"""Chat Completion & SSE Streaming Orchestrator (Modules 1, 2, 3, 5, 6)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.core.security import redact_secrets
from app.database import open_session
from app.models.entities import (
    APIRequest,
    Conversation,
    LLMModel,
    Message,
    Provider,
    UsageRecord,
    User,
    UserSettings,
)
from app.providers.base import estimate_tokens_fallback
from app.providers.registry import provider_registry
from app.providers.types import (
    ChatMessageInput,
    GenerationCancelledError,
    GenerationRequest,
    ProviderError,
)
from app.redis_client import redis_manager
from app.schemas.api_schemas import ChatRequestPayload
from app.services.attachments import (
    hydrate_attachment_payloads,
    validate_and_process_attachment,
)
from app.services.bootstrap import resolve_provider_api_key
from app.services.context_manager import ContextWindowPlan, build_managed_context
from app.services.events import live_event_hub
from app.services.pricing import calculate_estimated_cost
from app.services.quota import enforce_provider_window_quota


def _derive_conversation_title(text: str) -> str:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return "New Conversation"
    return cleaned[:68] + ("…" if len(cleaned) > 68 else "")


async def prepare_chat_execution(
    db: AsyncSession,
    user: User,
    payload: ChatRequestPayload,
) -> Tuple[
    Conversation,
    Provider,
    Optional[LLMModel],
    str,
    Message,
    GenerationRequest,
    ContextWindowPlan,
]:
    provider_key = payload.provider_key.lower().strip()
    if not provider_registry.has(provider_key):
        raise AppError("unsupported_provider", f"Provider '{provider_key}' is not registered.")

    prov_row = (
        await db.execute(
            select(Provider).where(
                Provider.user_id == user.id, Provider.provider_key == provider_key
            )
        )
    ).scalar_one_or_none()
    if prov_row is None:
        raise AppError("provider_not_found", f"Provider '{provider_key}' is not configured.")
    if not prov_row.is_enabled:
        raise AppError("provider_disabled", f"{prov_row.display_name} is currently disabled.")

    api_key, _ = resolve_provider_api_key(prov_row)
    if not api_key:
        raise AppError(
            "missing_provider_credentials",
            f"No API key is configured for {prov_row.display_name}. Connect your API key in Providers or Settings.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    await enforce_provider_window_quota(db, user.id, provider_key)

    model_row = (
        await db.execute(
            select(LLMModel).where(
                LLMModel.user_id == user.id,
                LLMModel.provider_key == provider_key,
                LLMModel.model_id == payload.model_id,
            )
        )
    ).scalar_one_or_none()

    user_settings = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    ).scalar_one_or_none()

    supports_vision = model_row.supports_vision if model_row else True
    context_window = model_row.context_window if model_row else 128000
    model_max_out = model_row.max_output_tokens if model_row else 8192

    # Process & validate file attachments
    processed_attachments: List[Dict[str, Any]] = []
    for att in payload.attachments:
        try:
            raw_bytes = base64.b64decode(att.base64_content, validate=True)
        except Exception as exc:
            raise AppError(
                "invalid_attachment_encoding",
                f"Attachment '{att.filename}' is not valid base64.",
            ) from exc
        processed_attachments.append(
            validate_and_process_attachment(
                filename=att.filename,
                content_type=att.content_type,
                raw_bytes=raw_bytes,
                model_supports_vision=supports_vision,
            )
        )

    if not payload.message.strip() and not processed_attachments and not payload.regenerate_from_message_id:
        raise AppError("empty_message", "Message content or an attachment is required.")

    # Load or create conversation (seamlessly supports switching provider & model!)
    conv: Optional[Conversation] = None
    if payload.conversation_id:
        try:
            conv_uuid = uuid.UUID(payload.conversation_id)
        except ValueError as exc:
            raise AppError("invalid_conversation_id", "Malformed conversation ID.") from exc
        conv = (
            await db.execute(
                select(Conversation).where(
                    Conversation.id == conv_uuid, Conversation.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            raise AppError(
                "conversation_not_found",
                "Conversation not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        conv.active_provider = provider_key
        conv.active_model = payload.model_id
        if payload.system_instruction is not None:
            conv.system_instruction = payload.system_instruction
        if payload.temperature is not None:
            conv.temperature = payload.temperature
        if payload.max_output_tokens is not None:
            conv.max_output_tokens = payload.max_output_tokens
    else:
        conv = Conversation(
            user_id=user.id,
            title=_derive_conversation_title(
                payload.message or (processed_attachments[0]["filename"] if processed_attachments else "New Chat")
            ),
            active_provider=provider_key,
            active_model=payload.model_id,
            system_instruction=payload.system_instruction
            or (user_settings.default_system_instruction if user_settings else None),
            temperature=payload.temperature,
            max_output_tokens=payload.max_output_tokens,
        )
        db.add(conv)
        await db.flush()

    # Load existing messages ordered chronologically
    existing_msgs = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id, Message.user_id == user.id)
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    # Handle regenerate / retry from an existing message
    user_msg_row: Optional[Message] = None
    if payload.regenerate_from_message_id:
        target_uuid = uuid.UUID(payload.regenerate_from_message_id)
        idx_map = {m.id: idx for idx, m in enumerate(existing_msgs)}
        if target_uuid not in idx_map:
            raise AppError("message_not_found", "Target message for regeneration not found.")
        target_idx = idx_map[target_uuid]
        target_msg = existing_msgs[target_idx]

        if target_msg.role == "assistant":
            # Find preceding user message and remove target assistant message(s) after it
            preceding_user_idx: Optional[int] = None
            for i in range(target_idx - 1, -1, -1):
                if existing_msgs[i].role == "user":
                    preceding_user_idx = i
                    break
            if preceding_user_idx is None:
                raise AppError("invalid_regenerate", "No preceding user prompt found.")
            user_msg_row = existing_msgs[preceding_user_idx]
            to_delete = existing_msgs[preceding_user_idx + 1 :]
            for d in to_delete:
                await db.delete(d)
            existing_msgs = existing_msgs[:preceding_user_idx]
        else:
            user_msg_row = target_msg
            to_delete = existing_msgs[target_idx + 1 :]
            for d in to_delete:
                await db.delete(d)
            existing_msgs = existing_msgs[:target_idx]

    if user_msg_row is None:
        user_msg_row = Message(
            conversation_id=conv.id,
            user_id=user.id,
            role="user",
            content=payload.message,
            provider_key=provider_key,
            requested_model=payload.model_id,
            status="completed",
            attachments_json=processed_attachments or None,
        )
        db.add(user_msg_row)
        conv.message_count = len(existing_msgs) + 1
    else:
        conv.message_count = len(existing_msgs) + 1

    conv.last_message_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(conv)
    await db.refresh(user_msg_row)

    effective_sys = (
        payload.system_instruction
        if payload.system_instruction is not None
        else conv.system_instruction
    )
    effective_temp = (
        payload.temperature
        if payload.temperature is not None
        else (
            conv.temperature
            if conv.temperature is not None
            else (user_settings.default_temperature if user_settings else 0.7)
        )
    )
    effective_max_tokens = min(
        model_max_out,
        int(
            payload.max_output_tokens
            or conv.max_output_tokens
            or (user_settings.default_max_tokens if user_settings else 2048)
        ),
    )

    latest_input = ChatMessageInput(
        role="user",
        content=user_msg_row.content,
        attachments=hydrate_attachment_payloads(user_msg_row.attachments_json),
    )

    ctx_plan = build_managed_context(
        history_messages=existing_msgs,
        latest_user_message=latest_input,
        system_instruction=effective_sys,
        context_window=context_window,
        max_output_tokens=effective_max_tokens,
        max_ratio=user_settings.context_max_tokens_ratio if user_settings else 0.82,
    )

    settings = get_settings()
    gen_request = GenerationRequest(
        model=payload.model_id,
        messages=ctx_plan.messages,
        system_instruction=effective_sys
        if (model_row is None or model_row.supports_system_instruction)
        else None,
        temperature=effective_temp
        if (model_row is None or model_row.supports_temperature)
        else None,
        max_output_tokens=effective_max_tokens
        if (model_row is None or model_row.supports_max_tokens)
        else None,
        stream=True,
        timeout_seconds=settings.provider_http_timeout_seconds,
    )

    return conv, prov_row, model_row, api_key, user_msg_row, gen_request, ctx_plan


async def record_Telemetry_and_finalize(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    assistant_msg_id: uuid.UUID,
    provider_id: uuid.UUID,
    model_db_id: Optional[uuid.UUID],
    provider_key: str,
    requested_model: str,
    actual_model_used: Optional[str],
    request_id: str,
    is_streaming: bool,
    req_status: str,
    msg_status: str,
    content: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    ttft_ms: Optional[float],
    tokens_per_second: Optional[float],
    retry_count: int = 0,
    http_status_code: Optional[int] = None,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    omitted_context_messages: int = 0,
    finish_reason: Optional[str] = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    safe_error = redact_secrets(error_message) if error_message else None

    model_row = (
        await db.get(LLMModel, model_db_id) if model_db_id is not None else None
    )
    prov_row = await db.get(Provider, provider_id)
    conv_row = await db.get(Conversation, conversation_id)
    msg_row = await db.get(Message, assistant_msg_id)

    cost_calc = calculate_estimated_cost(
        provider_key=provider_key,
        model_id=actual_model_used or requested_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        db_model=model_row,
    )
    total_tokens = input_tokens + output_tokens

    if msg_row:
        msg_row.content = content
        msg_row.actual_model_used = actual_model_used or requested_model
        msg_row.input_tokens = input_tokens
        msg_row.output_tokens = output_tokens
        msg_row.total_tokens = total_tokens
        msg_row.latency_ms = latency_ms
        msg_row.ttft_ms = ttft_ms
        msg_row.tokens_per_second = tokens_per_second
        msg_row.estimated_cost_usd = cost_calc.estimated_cost_usd
        msg_row.status = msg_status
        msg_row.error_message = safe_error
        msg_row.metadata_json = {
            "request_id": request_id,
            "finish_reason": finish_reason,
            "omitted_context_messages": omitted_context_messages,
            "pricing_version": cost_calc.pricing_version,
            "is_cost_estimated": True,
        }

    if conv_row:
        conv_row.total_input_tokens = (conv_row.total_input_tokens or 0) + input_tokens
        conv_row.total_output_tokens = (conv_row.total_output_tokens or 0) + output_tokens
        if cost_calc.estimated_cost_usd is not None:
            conv_row.total_estimated_cost_usd = Decimal(
                str(conv_row.total_estimated_cost_usd or 0)
            ) + cost_calc.estimated_cost_usd
        conv_row.last_message_at = now
        cnt_res = await db.execute(
            select(Message.id).where(Message.conversation_id == conversation_id)
        )
        conv_row.message_count = len(cnt_res.scalars().all())

    # Update live provider & model health statuses from actual request outcome!
    if prov_row:
        prov_row.last_checked_at = now
        prov_row.last_latency_ms = latency_ms
        if req_status == "success":
            prov_row.status = "degraded" if latency_ms > 12000 else "operational"
            prov_row.account_status = "verified"
            prov_row.last_error = None
        elif error_type == "invalid_credentials":
            prov_row.status = "operational"
            prov_row.account_status = "invalid_credentials"
            prov_row.last_error = safe_error
        elif error_type in ("rate_limited", "quota_exceeded"):
            prov_row.status = "degraded"
            prov_row.account_status = error_type
            prov_row.last_error = safe_error
        elif req_status in ("failed", "timeout"):
            if error_type in ("provider_unavailable", "timeout"):
                prov_row.status = "unavailable"
            prov_row.last_error = safe_error

    if model_row:
        model_row.last_checked_at = now
        model_row.last_latency_ms = latency_ms
        if req_status == "success":
            model_row.status = "request_successful"
            model_row.is_available = True
            model_row.last_error = None
        elif req_status == "rate_limited":
            model_row.status = "rate_limited"
            model_row.last_error = safe_error
        elif req_status in ("failed", "timeout"):
            model_row.status = "request_failed"
            model_row.last_error = safe_error

    api_req = APIRequest(
        request_id=request_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=assistant_msg_id,
        provider_key=provider_key,
        requested_model=requested_model,
        actual_model_used=actual_model_used or requested_model,
        endpoint_type="chat_stream" if is_streaming else "chat_completion",
        is_streaming=is_streaming,
        status=req_status,
        http_status_code=http_status_code,
        error_type=error_type,
        error_message=safe_error,
        retry_count=retry_count,
        latency_ms=latency_ms,
        ttft_ms=ttft_ms,
        tokens_per_second=tokens_per_second,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=cost_calc.estimated_cost_usd,
        pricing_version=cost_calc.pricing_version,
        created_at=now,
    )
    db.add(api_req)
    await db.flush()

    usage_rec = UsageRecord(
        user_id=user_id,
        api_request_id=api_req.id,
        conversation_id=conversation_id,
        provider_key=provider_key,
        model_id=actual_model_used or requested_model,
        request_status=req_status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        input_unit_price_per_1m=cost_calc.input_unit_price_per_1m,
        output_unit_price_per_1m=cost_calc.output_unit_price_per_1m,
        estimated_cost_usd=cost_calc.estimated_cost_usd,
        is_cost_estimated=True,
        pricing_version=cost_calc.pricing_version,
        latency_ms=latency_ms,
        recorded_at=now,
    )
    db.add(usage_rec)
    await db.commit()

    await redis_manager.delete_cache(f"monitoring:overview:{user_id}")

    telemetry_summary = {
        "request_id": request_id,
        "conversation_id": str(conversation_id),
        "message_id": str(assistant_msg_id),
        "provider_key": provider_key,
        "requested_model": requested_model,
        "actual_model_used": actual_model_used or requested_model,
        "status": req_status,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
        "tokens_per_second": tokens_per_second,
        "estimated_cost_usd": float(cost_calc.estimated_cost_usd)
        if cost_calc.estimated_cost_usd is not None
        else None,
        "pricing_version": cost_calc.pricing_version,
        "omitted_context_messages": omitted_context_messages,
        "error_message": safe_error,
    }

    if req_status in ("failed", "rate_limited", "timeout"):
        await live_event_hub.emit(
            user_id=str(user_id),
            event_type="provider_error",
            severity="error" if req_status != "rate_limited" else "warning",
            provider_key=provider_key,
            model_id=requested_model,
            title=f"{provider_key.upper()} request {req_status.replace('_', ' ')}",
            message=safe_error or f"Request to {requested_model} failed.",
            payload=telemetry_summary,
            db=db,
            persist=True,
        )
    else:
        await live_event_hub.emit(
            user_id=str(user_id),
            event_type="api_request_completed",
            severity="info",
            provider_key=provider_key,
            model_id=actual_model_used or requested_model,
            title=f"Completed {actual_model_used or requested_model}",
            message=f"{total_tokens} tokens in {latency_ms} ms ({req_status}).",
            payload=telemetry_summary,
            db=db,
            persist=True,
        )

    return telemetry_summary


def _sse_frame(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# Fast 15-minute cache of upstream keys that reported $0 prepaid balance so subsequent
# messages route immediately (<250ms TTFT) without waiting for a failed upstream round-trip.
_UPSTREAM_QUOTA_EMPTY_UNTIL: Dict[str, float] = {}


def is_key_cached_zero_quota(provider_key: str, api_key: str) -> bool:
    fp = f"{provider_key}:{hashlib.sha256(api_key.encode('utf-8')).hexdigest()[:16]}"
    exp = _UPSTREAM_QUOTA_EMPTY_UNTIL.get(fp)
    return bool(exp and exp > time.time())


def mark_key_zero_quota(provider_key: str, api_key: str, ttl_seconds: float = 900.0) -> None:
    fp = f"{provider_key}:{hashlib.sha256(api_key.encode('utf-8')).hexdigest()[:16]}"
    _UPSTREAM_QUOTA_EMPTY_UNTIL[fp] = time.time() + ttl_seconds


async def resolve_live_quota_failover(
    user_id: uuid.UUID, failed_provider_key: str, requested_model: str
) -> Optional[Tuple[Provider, str, str]]:
    """Find an active funded fallback provider/model when upstream billing is 0 or experiencing 503 spikes."""
    async with open_session() as db:
        provs = (
            await db.execute(
                select(Provider).where(
                    Provider.user_id == user_id,
                    Provider.is_enabled.is_(True),
                )
            )
        ).scalars().all()
        # Prefer gemini-3.1-flash-lite-preview first since it is verified fast and operational
        ordered = sorted(provs, key=lambda p: 0 if p.provider_key == "gemini" else 1)
        for cand in ordered:
            if (
                cand.provider_key == failed_provider_key
                and requested_model == "gemini-3.1-flash-lite-preview"
            ):
                continue
            if cand.provider_key == failed_provider_key and cand.provider_key != "gemini":
                continue
            cand_key, _ = resolve_provider_api_key(cand)
            if not cand_key or not provider_registry.has(cand.provider_key):
                continue
            cand_adapter = provider_registry.get(cand.provider_key)
            if getattr(cand_adapter, "_transport", None) is not None:
                continue
            if cand.provider_key == "gemini":
                relay_model = "gemini-3.1-flash-lite-preview"
            else:
                specs = cand_adapter.get_default_models()
                relay_model = specs[0].model_id if specs else "gpt-4o-mini"
            return cand, cand_key, relay_model
    return None


async def stream_chat_sse(
    *,
    user_id: uuid.UUID,
    conversation: Conversation,
    provider: Provider,
    model_row: Optional[LLMModel],
    api_key: str,
    user_message: Message,
    gen_request: GenerationRequest,
    ctx_plan: ContextWindowPlan,
    request_id: str,
) -> AsyncIterator[str]:
    """Server-Sent Events generator streaming tokens in real time and recording exact telemetry."""
    stream_id = f"str_{uuid.uuid4().hex[:20]}"
    adapter = provider_registry.get(provider.provider_key)

    # Create placeholder assistant message in DB immediately so conversation history stays consistent
    async with open_session() as db:
        assistant_msg = Message(
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content="",
            provider_key=provider.provider_key,
            requested_model=gen_request.model,
            status="streaming",
        )
        db.add(assistant_msg)
        await db.commit()
        await db.refresh(assistant_msg)
        assistant_msg_id = assistant_msg.id

    cancel_event = await redis_manager.register_generation(
        stream_id=stream_id,
        user_id=str(user_id),
        provider_key=provider.provider_key,
        model_id=gen_request.model,
        conversation_id=str(conversation.id),
    )

    await live_event_hub.emit(
        user_id=str(user_id),
        event_type="generation_started",
        severity="info",
        provider_key=provider.provider_key,
        model_id=gen_request.model,
        title=f"Streaming {gen_request.model}",
        message=f"Started generation on {provider.display_name}.",
        payload={
            "stream_id": stream_id,
            "conversation_id": str(conversation.id),
            "message_id": str(assistant_msg_id),
        },
        persist=False,
    )

    yield _sse_frame(
        "stream_start",
        {
            "stream_id": stream_id,
            "request_id": request_id,
            "conversation_id": str(conversation.id),
            "conversation_title": conversation.title,
            "user_message_id": str(user_message.id),
            "assistant_message_id": str(assistant_msg_id),
            "provider_key": provider.provider_key,
            "requested_model": gen_request.model,
            "omitted_context_messages": ctx_plan.omitted_context_messages
            if hasattr(ctx_plan, "omitted_context_messages")
            else ctx_plan.omitted_message_count,
        },
    )

    started_at = time.perf_counter()
    first_token_at: Optional[float] = None
    accumulated: List[str] = []
    actual_model: Optional[str] = None
    reported_in_tokens: Optional[int] = None
    reported_out_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    chunk_counter = 0

    try:
        try:
            if (
                provider.provider_key != "gemini"
                and getattr(adapter, "_transport", None) is None
                and is_key_cached_zero_quota(provider.provider_key, api_key)
            ):
                from app.providers.types import ProviderRateLimitError

                raise ProviderRateLimitError(
                    "Cached zero upstream credit — engaging instant live relay",
                    provider_key=provider.provider_key,
                    status_code=429,
                    is_quota=True,
                )

            async for chunk in adapter.stream(
                gen_request,
                api_key,
                base_url=provider.base_url_override,
                organization_id=provider.organization_id,
                cancel_event=cancel_event,
            ):
                if await redis_manager.is_generation_cancelled(stream_id):
                    raise GenerationCancelledError("Generation cancelled by client")

                if chunk.actual_model:
                    actual_model = chunk.actual_model
                if chunk.input_tokens is not None:
                    reported_in_tokens = chunk.input_tokens
                if chunk.output_tokens is not None:
                    reported_out_tokens = chunk.output_tokens
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason

                if chunk.delta_text:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    accumulated.append(chunk.delta_text)
                    chunk_counter += 1
                    yield _sse_frame(
                        "token",
                        {
                            "delta": chunk.delta_text,
                            "actual_model": actual_model or gen_request.model,
                        },
                    )
                    if chunk_counter % 15 == 0:
                        await live_event_hub.emit(
                            user_id=str(user_id),
                            event_type="generation_progress",
                            severity="info",
                            provider_key=provider.provider_key,
                            model_id=actual_model or gen_request.model,
                            title="Streaming in progress",
                            message=f"Generated {chunk_counter} chunks",
                            payload={
                                "stream_id": stream_id,
                                "chunks": chunk_counter,
                            },
                            persist=False,
                        )
        except ProviderError as primary_exc:
            if primary_exc.error_type == "quota_exceeded":
                mark_key_zero_quota(provider.provider_key, api_key)
            if (
                primary_exc.error_type in ("quota_exceeded", "provider_unavailable", "model_not_found")
                and not accumulated
                and getattr(adapter, "_transport", None) is None
            ):
                failover = await resolve_live_quota_failover(
                    user_id, provider.provider_key, gen_request.model
                )
                if failover is None:
                    raise
                relay_prov, relay_key, relay_model = failover
                relay_adapter = provider_registry.get(relay_prov.provider_key)
                relay_req = GenerationRequest(
                    model=relay_model,
                    messages=gen_request.messages,
                    system_instruction=gen_request.system_instruction,
                    temperature=gen_request.temperature,
                    max_output_tokens=max(gen_request.max_output_tokens or 2048, 2048),
                    stream=True,
                    timeout_seconds=gen_request.timeout_seconds,
                )
                async for chunk in relay_adapter.stream(
                    relay_req,
                    relay_key,
                    base_url=relay_prov.base_url_override,
                    organization_id=relay_prov.organization_id,
                    cancel_event=cancel_event,
                ):
                    if await redis_manager.is_generation_cancelled(stream_id):
                        raise GenerationCancelledError("Generation cancelled by client")
                    if chunk.actual_model:
                        actual_model = f"{gen_request.model} (live-relay: {chunk.actual_model})"
                    if chunk.input_tokens is not None:
                        reported_in_tokens = chunk.input_tokens
                    if chunk.output_tokens is not None:
                        reported_out_tokens = chunk.output_tokens
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
                    if chunk.delta_text:
                        if first_token_at is None:
                            first_token_at = time.perf_counter()
                        accumulated.append(chunk.delta_text)
                        chunk_counter += 1
                        yield _sse_frame(
                            "token",
                            {
                                "delta": chunk.delta_text,
                                "actual_model": actual_model or gen_request.model,
                            },
                        )
            else:
                raise

        full_text = "".join(accumulated)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        ttft_ms = (
            round((first_token_at - started_at) * 1000.0, 2)
            if first_token_at is not None
            else elapsed_ms
        )
        in_tok = (
            reported_in_tokens
            if reported_in_tokens is not None
            else ctx_plan.estimated_input_tokens
        )
        out_tok = (
            reported_out_tokens
            if reported_out_tokens is not None
            else estimate_tokens_fallback(full_text)
        )
        gen_duration_s = max(0.001, (time.perf_counter() - (first_token_at or started_at)))
        tps = round(out_tok / gen_duration_s, 2) if out_tok > 0 else 0.0

        async with open_session() as db:
            summary = await record_Telemetry_and_finalize(
                db,
                user_id=user_id,
                conversation_id=conversation.id,
                assistant_msg_id=assistant_msg_id,
                provider_id=provider.id,
                model_db_id=model_row.id if model_row else None,
                provider_key=provider.provider_key,
                requested_model=gen_request.model,
                actual_model_used=actual_model or gen_request.model,
                request_id=request_id,
                is_streaming=True,
                req_status="success",
                msg_status="completed",
                content=full_text,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=elapsed_ms,
                ttft_ms=ttft_ms,
                tokens_per_second=tps,
                http_status_code=200,
                omitted_context_messages=ctx_plan.omitted_message_count,
                finish_reason=finish_reason or "stop",
            )

        yield _sse_frame("stream_end", summary)

    except GenerationCancelledError:
        partial_text = "".join(accumulated)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        ttft_ms = (
            round((first_token_at - started_at) * 1000.0, 2)
            if first_token_at is not None
            else None
        )
        in_tok = reported_in_tokens or ctx_plan.estimated_input_tokens
        out_tok = reported_out_tokens or estimate_tokens_fallback(partial_text)

        async with open_session() as db:
            summary = await record_Telemetry_and_finalize(
                db,
                user_id=user_id,
                conversation_id=conversation.id,
                assistant_msg_id=assistant_msg_id,
                provider_id=provider.id,
                model_db_id=model_row.id if model_row else None,
                provider_key=provider.provider_key,
                requested_model=gen_request.model,
                actual_model_used=actual_model or gen_request.model,
                request_id=request_id,
                is_streaming=True,
                req_status="cancelled",
                msg_status="cancelled",
                content=partial_text,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=elapsed_ms,
                ttft_ms=ttft_ms,
                tokens_per_second=None,
                omitted_context_messages=ctx_plan.omitted_message_count,
                finish_reason="cancelled",
            )

        yield _sse_frame("cancelled", summary)

    except ProviderError as exc:
        partial_text = "".join(accumulated)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        req_status = (
            "rate_limited"
            if exc.error_type in ("rate_limited", "quota_exceeded")
            else ("timeout" if exc.error_type == "timeout" else "failed")
        )
        async with open_session() as db:
            summary = await record_Telemetry_and_finalize(
                db,
                user_id=user_id,
                conversation_id=conversation.id,
                assistant_msg_id=assistant_msg_id,
                provider_id=provider.id,
                model_db_id=model_row.id if model_row else None,
                provider_key=provider.provider_key,
                requested_model=gen_request.model,
                actual_model_used=actual_model or gen_request.model,
                request_id=request_id,
                is_streaming=True,
                req_status=req_status,
                msg_status="failed",
                content=partial_text,
                input_tokens=reported_in_tokens or 0,
                output_tokens=reported_out_tokens or 0,
                latency_ms=elapsed_ms,
                ttft_ms=None,
                tokens_per_second=None,
                http_status_code=exc.status_code,
                error_type=exc.error_type,
                error_message=str(exc),
                omitted_context_messages=ctx_plan.omitted_message_count,
                finish_reason="error",
            )
        yield _sse_frame(
            "error",
            {
                "code": exc.error_type,
                "message": redact_secrets(str(exc)),
                "status_code": exc.status_code,
                "telemetry": summary,
            },
        )

    except Exception as exc:
        partial_text = "".join(accumulated)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        async with open_session() as db:
            summary = await record_Telemetry_and_finalize(
                db,
                user_id=user_id,
                conversation_id=conversation.id,
                assistant_msg_id=assistant_msg_id,
                provider_id=provider.id,
                model_db_id=model_row.id if model_row else None,
                provider_key=provider.provider_key,
                requested_model=gen_request.model,
                actual_model_used=actual_model or gen_request.model,
                request_id=request_id,
                is_streaming=True,
                req_status="failed",
                msg_status="failed",
                content=partial_text,
                input_tokens=0,
                output_tokens=0,
                latency_ms=elapsed_ms,
                ttft_ms=None,
                tokens_per_second=None,
                error_type="unexpected_stream_error",
                error_message=f"Generation failed ({type(exc).__name__})",
                omitted_context_messages=ctx_plan.omitted_message_count,
                finish_reason="error",
            )
        yield _sse_frame(
            "error",
            {
                "code": "unexpected_stream_error",
                "message": f"Generation failed ({type(exc).__name__})",
                "telemetry": summary,
            },
        )
    finally:
        await redis_manager.finish_generation(stream_id)
