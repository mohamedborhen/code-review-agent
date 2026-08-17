"""Use-case service: MemorySummary generation at turn end (PHASE_3.md §4).

MemorySummary writes are triggered asynchronously or strictly at the end of a
conversation turn by this dedicated service — never by the read-only Context
Agent. In v1 this is a deterministic, dependency-free summarizer; a later
phase may swap in an LLM summarizer without touching the persistence port.
"""

from application.conversation_service.ports import ConversationStorePort
from domain.entities.conversation_entity import MemorySummary


async def summarize_conversation(
    conversation_id: int,
    *,
    store: ConversationStorePort,
    recent_messages: list[str],
) -> MemorySummary | None:
    """Build and persist a MemorySummary for the conversation.

    ``recent_messages`` is the plain-text run of messages since the last
    summary (caller extracts it from the persisted messages). Returns the
    created MemorySummary, or None when there is nothing to summarize.
    """
    if not recent_messages:
        return None

    up_to_id = _latest_message_id(store, conversation_id)
    summary_text = _summarize(recent_messages)

    return store.add_memory_summary(
        MemorySummary(
            conversation_id=conversation_id,
            summary_text=summary_text,
            summarized_up_to_message_id=up_to_id,
        )
    )


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
