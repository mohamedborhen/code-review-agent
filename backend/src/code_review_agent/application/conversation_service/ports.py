"""Layer 3 use-case ports for the conversation lifecycle (Phase 3).

Domain-shaped interfaces the Application layer calls and the Infrastructure
layer implements. Deliberately framework-free: no FastAPI, no MCP SDK, no
SQLModel — the infra_engineer fills these in.
"""

from typing import Protocol

from domain.entities.conversation_entity import (
    ContextRetrieval,
    Conversation,
    MemorySummary,
    Message,
    ToolCall,
)


class ConversationStorePort(Protocol):
    """Persistence for the conversation tables (infra: SQLModel + SQLite)."""

    def create_conversation(self, repo_id: str, user_id: str) -> Conversation: ...
    def get_conversation(self, conversation_id: int) -> Conversation | None: ...
    def next_order_index(self, conversation_id: int) -> int: ...
    def add_message(self, message: Message) -> Message: ...
    def add_tool_call(self, tool_call: ToolCall) -> ToolCall: ...
    def list_messages(self, conversation_id: int) -> list[Message]: ...
    def add_memory_summary(self, summary: MemorySummary) -> MemorySummary: ...


class ContextAgentPort(Protocol):
    """Read-only context recall (infra: Conversation FastMCP search_messages).

    Async because the MCP call goes over the wire; identity params are
    explicit and authorized server-side (PHASE_3.md §5.1).
    """

    async def search_context(
        self,
        conversation_id: int,
        user_id: str,
        repo_id: str,
        query: str,
        limit: int = 10,
    ) -> ContextRetrieval: ...


class ConversationAuditPort(Protocol):
    """AgentExecution audit rows for context-agent invocations (PHASE_3.md §7).

    Never logs message content or snippet text — only query/identity/counts.
    """

    def record_context_invocation(
        self,
        conversation_id: int,
        query: str,
        results_count: int,
        latency_ms: int,
        status: str,
    ) -> None: ...
