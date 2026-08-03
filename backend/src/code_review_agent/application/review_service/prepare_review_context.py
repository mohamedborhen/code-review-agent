"""Pre-flight: graph readiness + workspace path resolution.

This is the documented, blessed exception to Phase 2's async layer — it wraps
two Phase 1 *synchronous* services (GraphReadinessService + a direct SQLModel
lookup) from inside the async POST /review route. See AGENTS.md's async/sync
boundary section. Do not spread this pattern elsewhere.
"""

from fastapi import HTTPException
from sqlmodel import Session, select

from application.graph_build_service.graph_readiness_service import (
    GraphReadinessService,
    GraphStatusQueryPort,
)
from domain.entities.graph_build_status import GraphBuildStatus
from infrastructure.db.engine import engine
from infrastructure.db.models import GraphSnapshot, RepoWorkspace


class _GraphSnapshotStatusQueryPort:
    """Phase 1's GraphStatusQueryPort backed by the direct GraphSnapshot query
    the webhook flow uses. GraphReadinessService is defined but never
    instantiated in Phase 1, so it is constructed here.
    """

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


def prepare_review_context(repo_id: str, graph_commit_hash: str) -> str:
    """Return repo_root (local_path). Raises HTTPException if not ready."""
    with Session(engine) as session:
        statement = select(RepoWorkspace).where(RepoWorkspace.repo_id == repo_id)
        workspace = session.exec(statement).first()

    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")

    readiness_service = GraphReadinessService(_GraphSnapshotStatusQueryPort())
    if not readiness_service.is_ready(repo_id, graph_commit_hash):
        raise HTTPException(status_code=425, detail="Graph not ready for this commit yet")

    return workspace.local_path
