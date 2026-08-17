from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, text
from sqlmodel import Field, Index, SQLModel, UniqueConstraint

_SERVER_NOW = text("STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

class RepoWorkspace(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("repo_id", "branch"),)

    id: int | None = Field(default=None, primary_key=True)
    repo_id: str = Field(index=True)
    branch: str
    local_path: str
    last_synced_commit: str | None = None
    last_requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GraphSnapshot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    repo_id: str = Field(index=True)
    commit_hash: str
    status: str
    error_message: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class ReviewSession(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    repo_id: str
    graph_commit_hash: str
    request_type: str
    model: str | None = None  # root (orchestrator+aggregator) model spec, if known
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # --- lifecycle / audit (added in the session-lifecycle workstream) ---
    # status: "running" on creation, "completed" on success, "failed" on a
    # caught exception. Legacy rows created before this column existed stay NULL.
    status: str | None = None
    error: str | None = None  # exception text when status == "failed"
    duration_ms: int | None = None  # whole run_review wall time on success
    completed_at: datetime | None = None
    # JSON lists — what the routing policy required vs. which subagents actually
    # dispatched (from the parsed per-agent reports). Enables over-delegation
    # auditing from the DB without relying on the ephemeral event log.
    expected_agents: str | None = None
    dispatched_agents: str | None = None


class AgentExecution(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    review_session_id: int | None = Field(default=None, foreign_key="reviewsession.id")
    conversation_id: int | None = Field(default=None, foreign_key="Conversation.id")
    agent_name: str
    duration_ms: int
    confidence: float | None = None
    model: str | None = None  # the model that actually produced this agent's output
    result: str  # JSON-serialized via dataclasses.asdict() — see PHASE_2.md Agent Contracts
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Phase 3: conversation persistence (see PHASE_3.md §2) ---
# Table names are EXPLICIT PascalCase (__tablename__) so the FTS5
# external-content reference `content='Message'` and the exact PascalCase DDL
# requirement in the Phase 3 DoD both hold. SQLModel's default (lowercased
# class name) would silently produce `message`/`conversation` and break the
# FTS5 content= resolution.


class Conversation(SQLModel, table=True):
    __tablename__ = "Conversation"
    __table_args__ = (
        Index("idx_conversation_repo_user", "repo_id", "user_id"),
        CheckConstraint("status IN ('active','archived')", name="ck_conversation_status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    repo_id: str
    user_id: str
    status: str = Field(default="active", sa_column_kwargs={"server_default": text("'active'")})
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _SERVER_NOW})
    updated_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _SERVER_NOW})


class Message(SQLModel, table=True):
    __tablename__ = "Message"
    __table_args__ = (
        UniqueConstraint("conversation_id", "order_index", name="uq_message_order"),
        CheckConstraint("role IN ('user','assistant','system')", name="ck_message_role"),
        CheckConstraint(
            "event_type IN ('thinking','tool_use','final')", name="ck_message_event_type"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="Conversation.id", ondelete="CASCADE", index=True)
    role: str  # 'user' | 'assistant' | 'system'
    event_type: str  # 'thinking' | 'tool_use' | 'final'
    content: str
    order_index: int
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _SERVER_NOW})


class ToolCall(SQLModel, table=True):
    __tablename__ = "ToolCall"
    __table_args__ = (
        CheckConstraint("tool_status IN ('success','error')", name="ck_tool_call_status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    message_id: int = Field(foreign_key="Message.id", ondelete="CASCADE", index=True)
    tool_name: str
    tool_input: str | None = None
    tool_output: str | None = None
    tool_latency_ms: int | None = None
    tool_status: str | None = None  # 'success' | 'error'


class MemorySummary(SQLModel, table=True):
    __tablename__ = "MemorySummary"

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="Conversation.id", ondelete="CASCADE", index=True)
    summary_text: str
    summarized_up_to_message_id: int = Field(foreign_key="Message.id")
    created_at: datetime = Field(default_factory=_utcnow, sa_column_kwargs={"server_default": _SERVER_NOW})
