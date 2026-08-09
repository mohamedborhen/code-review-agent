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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentExecution(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    review_session_id: int = Field(foreign_key="reviewsession.id")
    agent_name: str
    duration_ms: int
    confidence: float | None = None
    result: str  # JSON-serialized via dataclasses.asdict() — see PHASE_2.md Agent Contracts
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
