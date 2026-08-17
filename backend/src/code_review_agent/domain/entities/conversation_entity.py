from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Conversation:
    repo_id: str
    user_id: str
    status: str = "active"  # 'active' | 'archived'
    created_at: datetime | None = None
    updated_at: datetime | None = None
    id: int | None = None


@dataclass
class Message:
    conversation_id: int
    role: str  # 'user' | 'assistant' | 'system'
    event_type: str  # 'thinking' | 'tool_use' | 'final'
    content: str
    order_index: int
    created_at: datetime | None = None
    id: int | None = None


@dataclass
class ToolCall:
    message_id: int
    tool_name: str
    tool_input: str | None = None
    tool_output: str | None = None
    tool_latency_ms: int | None = None
    tool_status: str | None = None  # 'success' | 'error'
    id: int | None = None


@dataclass
class MemorySummary:
    conversation_id: int
    summary_text: str
    summarized_up_to_message_id: int
    created_at: datetime | None = None
    id: int | None = None


@dataclass
class ContextRetrievalResult:
    """One search_messages hit, retaining message_id provenance (PHASE_3.md §6).

    Retrieved results are evidence, not conclusions — the caller must keep the
    message_id so the evidence can be traced back to the source message.
    """

    message_id: int
    role: str
    snippet: str
    created_at: str | None = None
    score: float = 0.0


@dataclass
class ContextRetrieval:
    """Outcome of a search_messages call: hits plus tool-level metadata.

    ``error`` mirrors the tool's contract ('not_found' | 'invalid_query'), or
    is None on success. ``latency_ms`` records tool wall time for the audit row.
    """

    conversation_id: int
    results: list[ContextRetrievalResult] = field(default_factory=list)
    error: str | None = None
    latency_ms: int = 0


@dataclass
class ConversationTurn:
    """One turn of POST /conversations/{id}/message.

    Request side: the user's message. Result side: the assistant's reply plus
    any tool calls the turn executed and the context evidence used.
    """

    conversation_id: int
    user_id: str
    repo_id: str
    user_message: str
    assistant_reply: str | None = None
    context: ContextRetrieval | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
