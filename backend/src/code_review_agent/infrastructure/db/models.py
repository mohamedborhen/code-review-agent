from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class RepoWorkspace(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    repo_id: str = Field(unique=True, index=True)
    local_path: str
    last_synced_commit: str | None = None
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
    review_session_id: int = Field(foreign_key="reviewsession.id")
    agent_name: str
    duration_ms: int
    confidence: float | None = None
    model: str | None = None  # the model that actually produced this agent's output
    result: str  # JSON-serialized via dataclasses.asdict() — see PHASE_2.md Agent Contracts
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
