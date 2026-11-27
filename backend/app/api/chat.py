"""Chat Completions, SSE Streaming, Cancellation, File Parsing, and Conversation CRUD Router."""

from __future__ import annotations

import base64
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import enforce_api_rate_limit
from app.core.errors import AppError
from app.database import get_db
from app.models.entities import Conversation, Message, User
from app.providers.registry import provider_registry
from app.providers.types import ProviderError
from app.redis_client import redis_manager
from app.schemas.api_schemas import (
    CancelGenerationRequest,
    ChatRequestPayload,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    MessageResponse,
)
from app.services.attachments import validate_and_process_attachment
from app.services.chat_service import (
    prepare_chat_execution,
    record_Telemetry_and_finalize,
    resolve_live_quota_failover,
    stream_chat_sse,
)

router = APIRouter(prefix="/api", tags=["Chat & Conversations"])


def _serialize_message(m: Message) -> MessageResponse:
    safe_atts = []
    for a in m.attachments_json or []:
        safe_atts.append(
            {
                "filename": a.get("filename"),
                "mime_type": a.get("mime_type"),
                "size_bytes": a.get("size_bytes"),
                "kind": a.get("kind"),
                "preview_url": (
                    f"data:{a.get('mime_type')};base64,{a.get('base64_data')}"
                    if a.get("kind") == "image" and a.get("base64_data")
                    else None
                ),
            }
        )
    return MessageResponse(
        id=str(m.id),
        conversation_id=str(m.conversation_id),
        role=m.role,
        content=m.content,
        provider_key=m.provider_key,
        requested_model=m.requested_model,
        actual_model_used=m.actual_model_used,
        input_tokens=m.input_tokens,
        output_tokens=m.output_tokens,
        total_tokens=m.total_tokens,
        latency_ms=m.latency_ms,
        ttft_ms=m.ttft_ms,
        tokens_per_second=m.tokens_per_second,
        estimated_cost_usd=float(m.estimated_cost_usd)
        if m.estimated_cost_usd is not None
        else None,
        status=m.status,
        error_message=m.error_message,
        attachments=safe_atts,
        metadata=m.metadata_json or {},
        created_at=m.created_at,
    )


def _serialize_conversation_summary(c: Conversation) -> ConversationSummaryResponse:
    in_tok = c.total_input_tokens or 0
    out_tok = c.total_output_tokens or 0
    return ConversationSummaryResponse(
        id=str(c.id),
        title=c.title,
        active_provider=c.active_provider,
        active_model=c.active_model,
        system_instruction=c.system_instruction,
        temperature=c.temperature,
        max_output_tokens=c.max_output_tokens,
        total_input_tokens=in_tok,
        total_output_tokens=out_tok,
        total_tokens=in_tok + out_tok,
        total_estimated_cost_usd=round(float(c.total_estimated_cost_usd or 0), 6),
        message_count=c.message_count or 0,
        is_pinned=c.is_pinned,
        last_message_at=c.last_message_at,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


# ---------------------------------------------------------------------------
# Chat Endpoints
# ---------------------------------------------------------------------------
@router.post("/chat/completions")
async def create_chat_completion(
    request: Request,
    payload: ChatRequestPayload,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    req_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:20]}")
    (
        conv,
        prov,
        model_row,
        api_key,
        user_msg,
        gen_req,
        ctx_plan,
    ) = await prepare_chat_execution(db, user, payload)

    assistant_msg = Message(
        conversation_id=conv.id,
        user_id=user.id,
        role="assistant",
        content="",
        provider_key=prov.provider_key,
        requested_model=gen_req.model,
        status="streaming",
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)

    adapter = provider_registry.get(prov.provider_key)
    try:
        try:
            result = await adapter.complete(
                gen_req,
                api_key,
                base_url=prov.base_url_override,
                organization_id=prov.organization_id,
            )
        except ProviderError as primary_exc:
            if (
                primary_exc.error_type in ("quota_exceeded", "provider_unavailable", "model_not_found")
                and getattr(adapter, "_transport", None) is None
            ):
                failover = await resolve_live_quota_failover(
                    user.id, prov.provider_key, gen_req.model
                )
                if failover is None:
                    raise
                relay_prov, relay_key, relay_model = failover
                relay_adapter = provider_registry.get(relay_prov.provider_key)
                from app.providers.types import GenerationRequest as GenReqType

                relay_req = GenReqType(
                    model=relay_model,
                    messages=gen_req.messages,
                    system_instruction=gen_req.system_instruction,
                    temperature=gen_req.temperature,
                    max_output_tokens=max(gen_req.max_output_tokens or 2048, 2048),
                    stream=False,
                    timeout_seconds=gen_req.timeout_seconds,
                )
                result = await relay_adapter.complete(
                    relay_req,
                    relay_key,
                    base_url=relay_prov.base_url_override,
                    organization_id=relay_prov.organization_id,
                )
                result.actual_model = f"{gen_req.model} (live-relay: {result.actual_model})"
            else:
                raise
        telemetry = await record_Telemetry_and_finalize(
            db,
            user_id=user.id,
            conversation_id=conv.id,
            assistant_msg_id=assistant_msg.id,
            provider_id=prov.id,
            model_db_id=model_row.id if model_row else None,
            provider_key=prov.provider_key,
            requested_model=gen_req.model,
            actual_model_used=result.actual_model,
            request_id=req_id,
            is_streaming=False,
            req_status="success",
            msg_status="completed",
            content=result.content,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            ttft_ms=result.ttft_ms,
            tokens_per_second=result.tokens_per_second,
            retry_count=result.retry_count,
            http_status_code=200,
            omitted_context_messages=ctx_plan.omitted_message_count,
            finish_reason=result.finish_reason,
        )
        await db.refresh(assistant_msg)
        return {
            "conversation_id": str(conv.id),
            "conversation_title": conv.title,
            "user_message": _serialize_message(user_msg),
            "assistant_message": _serialize_message(assistant_msg),
            "telemetry": telemetry,
        }
    except ProviderError as exc:
        req_status = (
            "rate_limited"
            if exc.error_type in ("rate_limited", "quota_exceeded")
            else ("timeout" if exc.error_type == "timeout" else "failed")
        )
        await record_Telemetry_and_finalize(
            db,
            user_id=user.id,
            conversation_id=conv.id,
            assistant_msg_id=assistant_msg.id,
            provider_id=prov.id,
            model_db_id=model_row.id if model_row else None,
            provider_key=prov.provider_key,
            requested_model=gen_req.model,
            actual_model_used=gen_req.model,
            request_id=req_id,
            is_streaming=False,
            req_status=req_status,
            msg_status="failed",
            content="",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            ttft_ms=None,
            tokens_per_second=None,
            http_status_code=exc.status_code,
            error_type=exc.error_type,
            error_message=str(exc),
            omitted_context_messages=ctx_plan.omitted_message_count,
            finish_reason="error",
        )
        http_code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if req_status == "rate_limited"
            else (
                status.HTTP_504_GATEWAY_TIMEOUT
                if req_status == "timeout"
                else status.HTTP_502_BAD_GATEWAY
            )
        )
        raise AppError(exc.error_type, str(exc), status_code=http_code) from exc


@router.post("/chat/stream")
async def stream_chat_completion(
    request: Request,
    payload: ChatRequestPayload,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    req_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:20]}")
    (
        conv,
        prov,
        model_row,
        api_key,
        user_msg,
        gen_req,
        ctx_plan,
    ) = await prepare_chat_execution(db, user, payload)

    generator = stream_chat_sse(
        user_id=user.id,
        conversation=conv,
        provider=prov,
        model_row=model_row,
        api_key=api_key,
        user_message=user_msg,
        gen_request=gen_req,
        ctx_plan=ctx_plan,
        request_id=req_id,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": req_id,
        },
    )


@router.post("/chat/cancel")
async def cancel_active_generation(
    payload: CancelGenerationRequest,
    user: User = Depends(enforce_api_rate_limit),
) -> Dict[str, Any]:
    cancelled = await redis_manager.cancel_generation(payload.stream_id, str(user.id))
    if not cancelled:
        raise AppError(
            "stream_not_found",
            "Active generation stream not found or already completed.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return {"status": "cancellation_requested", "stream_id": payload.stream_id}


@router.post("/chat/attachments/validate")
async def validate_uploaded_attachment(
    file: UploadFile = File(...),
    user: User = Depends(enforce_api_rate_limit),
) -> Dict[str, Any]:
    raw_bytes = await file.read()
    processed = validate_and_process_attachment(
        filename=file.filename or "attachment",
        content_type=file.content_type or "application/octet-stream",
        raw_bytes=raw_bytes,
        model_supports_vision=True,
    )
    return {
        "filename": processed["filename"],
        "mime_type": processed["mime_type"],
        "size_bytes": processed["size_bytes"],
        "kind": processed["kind"],
        "base64_content": base64.b64encode(raw_bytes).decode("ascii"),
        "extracted_preview": (processed["extracted_text"] or "")[:300]
        if processed["extracted_text"]
        else None,
    }


# ---------------------------------------------------------------------------
# Conversation Management Endpoints
# ---------------------------------------------------------------------------
@router.get("/conversations")
async def list_conversations(
    search: Optional[str] = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=40, ge=1, le=100),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    stmt = select(Conversation).where(Conversation.user_id == user.id)
    if search and search.strip():
        q = f"%{search.strip()}%"
        msg_conv_subq = (
            select(Message.conversation_id)
            .where(Message.user_id == user.id, Message.content.ilike(q))
            .distinct()
        )
        stmt = stmt.where(
            or_(Conversation.title.ilike(q), Conversation.id.in_(msg_conv_subq))
        )

    stmt = stmt.order_by(
        desc(Conversation.is_pinned),
        desc(Conversation.updated_at),
    )
    all_rows = list((await db.execute(stmt)).scalars().all())
    total = len(all_rows)
    offset = (page - 1) * page_size
    items = [_serialize_conversation_summary(c) for c in all_rows[offset : offset + page_size]]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post(
    "/conversations",
    response_model=ConversationSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreateRequest,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> ConversationSummaryResponse:
    conv = Conversation(
        user_id=user.id,
        title=(payload.title or "New Conversation").strip(),
        active_provider=payload.provider_key.lower().strip(),
        active_model=payload.model_id.strip(),
        system_instruction=payload.system_instruction,
        temperature=payload.temperature,
        max_output_tokens=payload.max_output_tokens,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return _serialize_conversation_summary(conv)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailResponse:
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise AppError("invalid_conversation_id", "Invalid conversation UUID.") from exc

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

    msgs = list(
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
    summary = _serialize_conversation_summary(conv)
    return ConversationDetailResponse(
        **summary.model_dump(),
        messages=[_serialize_message(m) for m in msgs],
    )


@router.patch(
    "/conversations/{conversation_id}", response_model=ConversationSummaryResponse
)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdateRequest,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> ConversationSummaryResponse:
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise AppError("invalid_conversation_id", "Invalid conversation UUID.") from exc

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

    if payload.title is not None:
        conv.title = payload.title.strip()
    if payload.active_provider is not None:
        conv.active_provider = payload.active_provider.lower().strip()
    if payload.active_model is not None:
        conv.active_model = payload.active_model.strip()
    if "system_instruction" in payload.model_fields_set:
        conv.system_instruction = payload.system_instruction
    if "temperature" in payload.model_fields_set:
        conv.temperature = payload.temperature
    if "max_output_tokens" in payload.model_fields_set:
        conv.max_output_tokens = payload.max_output_tokens
    if payload.is_pinned is not None:
        conv.is_pinned = payload.is_pinned

    await db.commit()
    await db.refresh(conv)
    return _serialize_conversation_summary(conv)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise AppError("invalid_conversation_id", "Invalid conversation UUID.") from exc

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

    await db.delete(conv)
    await db.commit()
    return {"status": "deleted", "id": conversation_id}


@router.get("/conversations/{conversation_id}/export")
async def export_conversation(
    conversation_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    user: User = Depends(enforce_api_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Any:
    detail = await get_conversation(conversation_id, user=user, db=db)
    if format == "json":
        return detail.model_dump(mode="json")

    lines = [
        f"# {detail.title}",
        "",
        f"- **Active Provider / Model**: `{detail.active_provider}` / `{detail.active_model}`",
        f"- **Total Tokens**: {detail.total_tokens:,} ({detail.total_input_tokens:,} in / {detail.total_output_tokens:,} out)",
        f"- **Estimated Cost**: ${detail.total_estimated_cost_usd:.6f} USD (estimate)",
        f"- **Exported From**: LLM Control Center",
        "",
        "---",
        "",
    ]
    for m in detail.messages:
        role_heading = "User" if m.role == "user" else f"Assistant ({m.actual_model_used or m.requested_model or 'LLM'})"
        lines.append(f"### {role_heading} — {m.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append("")
        lines.append(m.content or "_[Empty]_")
        if m.role == "assistant" and m.total_tokens:
            lines.append("")
            lines.append(
                f"> Tokens: {m.total_tokens} ({m.input_tokens} in / {m.output_tokens} out) "
                f"| Latency: {m.latency_ms or 0} ms | TTFT: {m.ttft_ms or 0} ms"
            )
        lines.append("")
    return PlainTextResponse(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
    )
