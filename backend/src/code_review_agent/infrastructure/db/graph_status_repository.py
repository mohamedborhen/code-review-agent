"""SQLModel-backed graph-status query for graph readiness (Layer 5).

Phase 1 defines GraphReadinessService but never instantiates it; the review
route now composes it with this adapter — the direct GraphSnapshot query the
webhook flow uses, returning the domain GraphBuildStatus entity.
"""

from sqlmodel import Session, select

from domain.entities.graph_build_status import GraphBuildStatus
from infrastructure.db.engine import engine
from infrastructure.db.models import GraphSnapshot


class SQLModelGraphStatusQuery:
    def get_status(self, repo_id: str, commit_hash: str) -> GraphBuildStatus | None:
        with Session(engine) as session:
            statement = (
                select(GraphSnapshot)
                .where(
                    GraphSnapshot.repo_id == repo_id,
                    GraphSnapshot.commit_hash == commit_hash,
                )
                .order_by(GraphSnapshot.id.desc())
            )
            snapshot = session.exec(statement).first()
        if snapshot is None:
            return None
        return GraphBuildStatus(
            commit_hash=snapshot.commit_hash,
            status=snapshot.status,
            error_message=snapshot.error_message,
            started_at=snapshot.started_at,
            completed_at=snapshot.completed_at,
        )
