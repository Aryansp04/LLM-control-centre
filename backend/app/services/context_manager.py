"""Conversation context window manager.

Prevents context-window overflows by budgeting prompt tokens for system instructions,
reserved output capacity, and recent conversation history without sending stale/failed turns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.core.errors import AppError
from app.models.entities import Message
from app.providers.base import estimate_tokens_fallback
from app.providers.types import ChatMessageInput
from app.services.attachments import hydrate_attachment_payloads


@dataclass
class ContextWindowPlan:
    messages: List[ChatMessageInput]
    omitted_message_count: int
    estimated_input_tokens: int
    budget_tokens: int


def _estimate_message_tokens(msg: ChatMessageInput) -> int:
    total = estimate_tokens_fallback(msg.content) + 6
    for att in msg.attachments:
        if att.extracted_text:
            total += estimate_tokens_fallback(att.extracted_text) + 12
        elif att.kind == "image":
            # Standard multimodal image tile budget estimate
            total += 765
    return total


def build_managed_context(
    *,
    history_messages: List[Message],
    latest_user_message: ChatMessageInput,
    system_instruction: Optional[str],
    context_window: int,
    max_output_tokens: int,
    max_ratio: float = 0.82,
) -> ContextWindowPlan:
    safe_ratio = max(0.3, min(0.95, max_ratio))
    reserved_output = min(max_output_tokens, context_window // 2)
    available_budget = max(512, int(context_window * safe_ratio) - reserved_output)

    sys_tokens = (
        estimate_tokens_fallback(system_instruction) + 8 if system_instruction else 0
    )
    latest_tokens = _estimate_message_tokens(latest_user_message)

    if sys_tokens + latest_tokens > context_window - 128:
        raise AppError(
            code="context_window_exceeded",
            message=(
                f"Your prompt and attachments (~{sys_tokens + latest_tokens:,} tokens) exceed "
                f"the selected model's context window ({context_window:,} tokens)."
            ),
            details={
                "estimated_prompt_tokens": sys_tokens + latest_tokens,
                "context_window": context_window,
            },
        )

    remaining_for_history = max(0, available_budget - sys_tokens - latest_tokens)

    eligible_history: List[ChatMessageInput] = []
    for m in history_messages:
        if m.status not in ("completed", "cancelled") or not (m.content or m.attachments_json):
            continue
        if m.role not in ("user", "assistant"):
            continue
        eligible_history.append(
            ChatMessageInput(
                role=m.role,
                content=m.content,
                attachments=hydrate_attachment_payloads(m.attachments_json),
            )
        )

    selected_reversed: List[ChatMessageInput] = []
    used_history_tokens = 0
    omitted = 0

    for idx in range(len(eligible_history) - 1, -1, -1):
        candidate = eligible_history[idx]
        cost = _estimate_message_tokens(candidate)
        if used_history_tokens + cost <= remaining_for_history:
            selected_reversed.append(candidate)
            used_history_tokens += cost
        else:
            omitted = idx + 1
            break

    selected_history = list(reversed(selected_reversed))
    # Ensure first message in context is from 'user' (required by Anthropic/Gemini turn alternation)
    while selected_history and selected_history[0].role != "user":
        dropped = selected_history.pop(0)
        used_history_tokens = max(0, used_history_tokens - _estimate_message_tokens(dropped))
        omitted += 1

    final_messages = selected_history + [latest_user_message]
    return ContextWindowPlan(
        messages=final_messages,
        omitted_message_count=omitted,
        estimated_input_tokens=sys_tokens + used_history_tokens + latest_tokens,
        budget_tokens=available_budget,
    )
