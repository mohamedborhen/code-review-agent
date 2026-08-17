"""SQLModel-backed adapter for ConversationStorePort (Layer 5, Phase 3).

Implements the Application-layer port from
application/conversation_service/ports.py. Persistence runs in explicit
transaction boundaries; order_index monotonicity is guaranteed by
``next_order_index`` (read max + 1) combined with the table's
``UNIQUE(conversation_id, order_index)`` constraint (PHASE_3.md §2.1, §4).
"""

from datetime import datetime, timezone

from sqlmodel import Session, func, select

from domain.entities.conversation_entity import (
    Conversation,
    MemorySummary,
    Message,
    ToolCall,
)
from infrastructure.db.engine import engine
from infrastructure.db.models import (
    Conversation as ConversationTable,
    MemorySummary as MemorySummaryTable,
    Message as MessageTable,
    ToolCall as ToolCallTable,
)


class SQLModelConversationRepository:
    """Implements ConversationStorePort against the Phase 1 SQLite DB."""

    def __init__(self, engine=engine) -> None:
        # Injectable engine for tests (see tests/test_repo_workspace_repository.py);
        # production callers use the shared global engine.
        self._engine = engine

    def create_conversation(self, repo_id: str, user_id: str) -> Conversation:
        with Session(self._engine) as session:
            row = ConversationTable(repo_id=repo_id, user_id=user_id)
            session.add(row)
            session.commit()
            session.refresh(row)
        return _to_conversation(row)

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        with Session(self._engine) as session:
            row = session.get(ConversationTable, conversation_id)
        return _to_conversation(row)

    def next_order_index(self, conversation_id: int) -> int:
        """Max order_index for the conversation, plus one (monotonic)."""
        with Session(self._engine) as session:
            current = session.exec(
                select(func.max(MessageTable.order_index)).where(
                    MessageTable.conversation_id == conversation_id
                )
            ).one()
        return (current or 0) + 1

    def add_message(self, message: Message) -> Message:
        with Session(self._engine) as session:
            row = MessageTable(
                conversation_id=message.conversation_id,
                role=message.role,
                event_type=message.event_type,
                content=message.content,
                order_index=message.order_index,
                created_at=message.created_at or datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return _to_message(row)

    def add_tool_call(self, tool_call: ToolCall) -> ToolCall:
        with Session(self._engine) as session:
            row = ToolCallTable(
                message_id=tool_call.message_id,
                tool_name=tool_call.tool_name,
                tool_input=tool_call.tool_input,
                tool_output=tool_call.tool_output,
                tool_latency_ms=tool_call.tool_latency_ms,
                tool_status=tool_call.tool_status,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return _to_tool_call(row)

    def list_messages(self, conversation_id: int) -> list[Message]:
        with Session(self._engine) as session:
            rows = session.exec(
                select(MessageTable)
                .where(MessageTable.conversation_id == conversation_id)
                .order_by(MessageTable.id.asc())
            ).all()
        return [_to_message(row) for row in rows]

    def add_memory_summary(self, summary: MemorySummary) -> MemorySummary:
        with Session(self._engine) as session:
            row = MemorySummaryTable(
                conversation_id=summary.conversation_id,
                summary_text=summary.summary_text,
                summarized_up_to_message_id=summary.summarized_up_to_message_id,
                created_at=summary.created_at or datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return _to_memory_summary(row)


def _to_conversation(row: ConversationTable | None) -> Conversation | None:
    if row is None:
        return None
    return Conversation(
        id=row.id,
        repo_id=row.repo_id,
        user_id=row.user_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_message(row: MessageTable) -> Message:
    return Message(
        id=row.id,
        conversation_id=row.conversation_id,
        role=row.role,
        event_type=row.event_type,
        content=row.content,
        order_index=row.order_index,
        created_at=row.created_at,
    )


def _to_tool_call(row: ToolCallTable) -> ToolCall:
    return ToolCall(
        id=row.id,
        message_id=row.message_id,
        tool_name=row.tool_name,
        tool_input=row.tool_input,
        tool_output=row.tool_output,
        tool_latency_ms=row.tool_latency_ms,
        tool_status=row.tool_status,
    )


def _to_memory_summary(row: MemorySummaryTable) -> MemorySummary:
    return MemorySummary(
        id=row.id,
        conversation_id=row.conversation_id,
        summary_text=row.summary_text,
        summarized_up_to_message_id=row.summarized_up_to_message_id,
        created_at=row.created_at,
    )