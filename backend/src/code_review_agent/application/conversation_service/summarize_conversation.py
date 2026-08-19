"""Use-case service: MemorySummary generation at turn end (PHASE_3.md §4).

MemorySummary writes are triggered asynchronously or strictly at the end of a
conversation turn by this dedicated service — never by the read-only Context
Agent. The summarizer accepts an injected async LLM callable (built by the
infrastructure layer around ``settings.review_model``); on timeout/provider
error or an empty result it falls back to the deterministic tail-summary v1
already in this module — a memory-summary failure must never fail the review
(PHASE_4.md §5.3).
"""

from collections.abc import Awaitable, Callable

from application.conversation_service.ports import ConversationStorePort
from domain.entities.conversation_entity import MemorySummary


async def summarize_conversation(
    conversation_id: int,
    *,
    store: ConversationStorePort,
    recent_messages: list[str],
    llm_summarizer: Callable[[list[str]], Awaitable[str]] | None = None,
) -> MemorySummary | None:
    """Build and persist a MemorySummary for the conversation.

    ``recent_messages`` is the plain-text run of messages since the last
    summary (caller extracts it from the persisted messages). Returns the
    created MemorySummary, or None when there is nothing to summarize.

    ``llm_summarizer`` is injected by the infrastructure layer and stays
    framework-free here: an async callable ``list[str] -> str`` that turns the
    plain-text run into a summary. When provided it is attempted first; on ANY
    exception (timeout/provider error) or an empty/None result, the
    deterministic tail-summary v1 (``_summarize``) is used instead, so a
    memory-summary failure never fails the review (PHASE_4.md §5.3).
    """
    if not recent_messages:
        return None

    up_to_id = _latest_message_id(store, conversation_id)
    summary_text = await _summarize_with_fallback(recent_messages, llm_summarizer)

    return store.add_memory_summary(
        MemorySummary(
            conversation_id=conversation_id,
            summary_text=summary_text,
            summarized_up_to_message_id=up_to_id,
        )
    )


async def _summarize_with_fallback(
    recent_messages: list[str],
    llm_summarizer: Callable[[list[str]], Awaitable[str]] | None,
) -> str:
    """LLM-first, deterministic-tail fallback (PHASE_4.md §5.3).

    Attempts the injected LLM summarizer; on any exception or an empty/None
    result, falls back to the deterministic v1 tail summary so a
    memory-summary failure never fails the review.
    """
    if llm_summarizer is not None:
        try:
            summary_text = (await llm_summarizer(recent_messages)).strip()
        except Exception:
            summary_text = ""
        if summary_text:
            return summary_text
    return _summarize(recent_messages)


def _latest_message_id(store: ConversationStorePort, conversation_id: int) -> int:
    """Highest message id for the conversation (recency wins, PHASE_3.md §7)."""
    messages = store.list_messages(conversation_id)
    return messages[-1].id if messages else 0


def _summarize(recent_messages: list[str]) -> str:
    """Deterministic v1 summarizer: keep the tail, mark the truncation.

    Message content is stored here in MemorySummary.summary_text, which is NOT
    an audit table — the audit-privacy rule (PHASE_3.md §7) forbids content in
    AgentExecution only.
    """
    if len(recent_messages) == 1:
        return recent_messages[0]
    head = recent_messages[:-1]
    tail = recent_messages[-1]
    return f"[{len(head)} earlier message(s) summarized] {tail}"
