"""Use-case service that runs one conversation turn (PHASE_3.md §4, §6).

Write path is Application-layer-only: user and assistant Messages plus any
ToolCall rows are persisted here, never inside the read-only Context Agent.
Identity (user_id/repo_id) is forwarded verbatim into search_messages, where
the §5.1 authorization check runs.

Threadpool boundary (AGENTS.md / PHASE_3.md §1): every synchronous SQLite
persistence call is offloaded via ``asyncio.to_thread`` so the FastAPI event
loop is never blocked. The Context Agent call is async by nature (wire call).
"""

import asyncio
import time
from datetime import datetime, timezone

from application.conversation_service.ports import (
    ContextAgentPort,
    ConversationAuditPort,
    ConversationStorePort,
)
from domain.entities.conversation_entity import (
    ContextRetrieval,
    Message,
    ToolCall,
)


async def run_conversation_turn(
    conversation_id: int,
    user_id: str,
    repo_id: str,
    user_message: str,
    *,
    store: ConversationStorePort,
    context_agent: ContextAgentPort,
    audit: ConversationAuditPort,
    max_context_results: int = 10,
) -> dict:
    """Persist the user's message, recall context if needed, and return the turn.

    Returns a serializable dict for the API layer:
        {
          "conversation_id": int,
          "user_message": str,
          "assistant_reply": str,
          "context": {...} | None,   # ContextRetrieval as plain dict
          "tool_calls": [ {...}, ... ]   # ToolCall rows created this turn
        }
    """

    conversation = await asyncio.to_thread(store.get_conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(conversation_id)

    order_index = await asyncio.to_thread(store.next_order_index, conversation_id)
    user_message_row = Message(
        conversation_id=conversation_id,
        role="user",
        event_type="final",
        content=user_message,
        order_index=order_index,
        created_at=datetime.now(timezone.utc),
    )
    await asyncio.to_thread(store.add_message, user_message_row)

    # Recall context when the user explicitly references history, and always
    # as cheap background evidence (PHASE_3.md §6: triggered when historical
    # context is missing or referenced).
    context = await _recall_context(
        conversation_id=conversation_id,
        user_id=user_id,
        repo_id=repo_id,
        query=user_message,
        context_agent=context_agent,
        audit=audit,
        limit=max_context_results,
    )

    assistant_reply = _synthesize_reply(user_message, context)
    reply_index = await asyncio.to_thread(store.next_order_index, conversation_id)
    reply_message = await asyncio.to_thread(
        store.add_message,
        Message(
            conversation_id=conversation_id,
            role="assistant",
            event_type="final",
            content=assistant_reply,
            order_index=reply_index,
            created_at=datetime.now(timezone.utc),
        ),
    )

    tool_calls: list[ToolCall] = []
    if context is not None and context.results:
        tool_call = await asyncio.to_thread(
            store.add_tool_call,
            ToolCall(
                message_id=reply_message.id or 0,
                tool_name="search_messages",
                tool_input=user_message[:200],
                tool_output=_summarize_snippets(context),
                tool_latency_ms=context.latency_ms,
                tool_status="success" if context.error is None else "error",
            ),
        )
        tool_calls.append(tool_call)

    return {
        "conversation_id": conversation_id,
        "user_message": user_message,
        "assistant_reply": assistant_reply,
        "context": _as_dict(context),
        "tool_calls": [tc.__dict__ for tc in tool_calls],
    }


async def _recall_context(
    *,
    conversation_id: int,
    user_id: str,
    repo_id: str,
    query: str,
    context_agent: ContextAgentPort,
    audit: ConversationAuditPort,
    limit: int,
) -> ContextRetrieval | None:
    started = time.monotonic()
    try:
        retrieval = await context_agent.search_context(
            conversation_id=conversation_id,
            user_id=user_id,
            repo_id=repo_id,
            query=query,
            limit=limit,
        )
    except Exception as exc:
        # Recall is evidence-gathering, never a turn-fatal failure. Audit the
        # failure (required by PHASE_3.md §7) and continue without context.
        latency_ms = int((time.monotonic() - started) * 1000)
        await asyncio.to_thread(
            audit.record_context_invocation,
            conversation_id,
            query,
            0,
            latency_ms,
            f"error:{type(exc).__name__}",
        )
        return None

    await asyncio.to_thread(
        audit.record_context_invocation,
        conversation_id,
        query,
        len(retrieval.results),
        retrieval.latency_ms,
        "ok" if retrieval.error is None else retrieval.error,
    )
    return retrieval


def _summarize_snippets(retrieval: ContextRetrieval) -> str:
    if not retrieval.results:
        return ""
    joined = " || ".join(r.snippet for r in retrieval.results[:3])
    return joined[:4000]


def _synthesize_reply(user_message: str, context: ContextRetrieval | None) -> str:
    """Turn-reply synthesis.

    PHASE_3.md §6 precedence: search_messages exact matches outrank MemorySummary,
    and the most recent message wins on contradiction. This minimal synthesizer
    surfaces the recalled evidence without an LLM; a summarizer pipeline may
    replace it in later phases.
    """
    if context is None or context.error is not None or not context.results:
        return (
            "Understood. I don't have recalled context for this turn — "
            "I'll answer from current knowledge."
        )
    best = context.results[0]
    return (
        f"Recalled from conversation history (message #{best.message_id}): "
        f"{best.snippet}"
    )


def _as_dict(retrieval: ContextRetrieval | None) -> dict | None:
    if retrieval is None:
        return None
    return {
        "conversation_id": retrieval.conversation_id,
        "results": [
            {
                "message_id": r.message_id,
                "role": r.role,
                "snippet": r.snippet,
                "created_at": r.created_at,
                "score": r.score,
            }
            for r in retrieval.results
        ],
        "error": retrieval.error,
        "latency_ms": retrieval.latency_ms,
    }


class ConversationNotFoundError(Exception):
    def __init__(self, conversation_id: int) -> None:
        super().__init__(f"Conversation {conversation_id} not found")
        self.conversation_id = conversation_id
