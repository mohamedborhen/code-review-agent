"""SQLModel-backed adapter for RepoWorkspaceQueryPort (Layer 5).

Implements the domain port from domain/review/review_context_ports.py. The
query itself is the same Phase 1 `select(RepoWorkspace)...` the webhook flow
uses — it is only relocated here so the Application layer never touches SQL.

Per-branch since the Branch-Aware addendum: each row is one (repo_id, branch)
worktree (or the base clone, which is the row for the repo's default branch).
`get_by_repo_id` is deliberately scoped to the base-clone row so callers that
review "the repo" against a graph_commit_hash keep Phase 1's semantics even
though the table now holds multiple rows per repo_id.
"""

from sqlmodel import Session, select

from domain.entities.repo_workspace import RepoWorkspace
from infrastructure.db.engine import engine
from infrastructure.db.models import RepoWorkspace as RepoWorkspaceTable


class SQLModelRepoWorkspaceRepository:
    def get_by_repo_id(self, repo_id: str) -> RepoWorkspace | None:
        # The base clone is the first row registered for a repo_id (created by
        # the registration flow before any worktree rows). Ordering by id.asc()
        # deterministically picks that row — the default-branch row — rather than
        # whatever row the query happens to return first.
        with Session(engine) as session:
            statement = (
                select(RepoWorkspaceTable)
                .where(RepoWorkspaceTable.repo_id == repo_id)
                .order_by(RepoWorkspaceTable.id.asc())
            )
            row = session.exec(statement).first()
        return _to_entity(row)

    def get_by_repo_id_and_branch(self, repo_id: str, branch: str) -> RepoWorkspace | None:
        with Session(engine) as session:
            statement = select(RepoWorkspaceTable).where(
                RepoWorkspaceTable.repo_id == repo_id,
                RepoWorkspaceTable.branch == branch,
            )
            row = session.exec(statement).first()
        return _to_entity(row)

    def repo_is_registered(self, repo_id: str) -> bool:
        with Session(engine) as session:
            statement = select(RepoWorkspaceTable.id).where(
                RepoWorkspaceTable.repo_id == repo_id
            )
            return session.exec(statement).first() is not None

    def add_worktree_row(
        self,
        repo_id: str,
        branch: str,
        local_path: str,
        last_synced_commit: str,
    ) -> None:
        """Insert a new per-branch workspace row (first build of a worktree)."""
        from datetime import datetime, timezone

        with Session(engine) as session:
            session.add(
                RepoWorkspaceTable(
                    repo_id=repo_id,
                    branch=branch,
                    local_path=local_path,
                    last_synced_commit=last_synced_commit,
                    last_requested_at=datetime.now(timezone.utc),
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

    def update_synced_commit(
        self,
        repo_id: str,
        branch: str,
        last_synced_commit: str,
    ) -> None:
        """Record a successful build for an existing (repo_id, branch) row."""
        from datetime import datetime, timezone

        with Session(engine) as session:
            statement = select(RepoWorkspaceTable).where(
                RepoWorkspaceTable.repo_id == repo_id,
                RepoWorkspaceTable.branch == branch,
            )
            row = session.exec(statement).first()
            if row is None:
                return
            row.last_synced_commit = last_synced_commit
            row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def touch_requested_at(self, repo_id: str, branch: str) -> None:
        """Update last_requested_at for eviction LRU ordering (§11)."""
        from datetime import datetime, timezone

        with Session(engine) as session:
            statement = select(RepoWorkspaceTable).where(
                RepoWorkspaceTable.repo_id == repo_id,
                RepoWorkspaceTable.branch == branch,
            )
            row = session.exec(statement).first()
            if row is None:
                return
            row.last_requested_at = datetime.now(timezone.utc)
            session.commit()

    def delete_branch_row(self, repo_id: str, branch: str) -> None:
        """Remove the (repo_id, branch) row (branch deletion cleanup, §9)."""
        with Session(engine) as session:
            statement = select(RepoWorkspaceTable).where(
                RepoWorkspaceTable.repo_id == repo_id,
                RepoWorkspaceTable.branch == branch,
            )
            row = session.exec(statement).first()
            if row is not None:
                session.delete(row)
                session.commit()

    def record_graph_snapshot(
        self,
        repo_id: str,
        commit_hash: str,
        status: str,
        error_message: str | None,
    ) -> None:
        """Write a GraphSnapshot row so graph readiness can be queried."""
        from datetime import datetime, timezone

        from infrastructure.db.models import GraphSnapshot

        with Session(engine) as session:
            session.add(
                GraphSnapshot(
                    repo_id=repo_id,
                    commit_hash=commit_hash,
                    status=status,
                    error_message=error_message,
                    completed_at=datetime.now(timezone.utc) if status == "ready" else None,
                )
            )
            session.commit()


def _to_entity(row: RepoWorkspaceTable | None) -> RepoWorkspace | None:
    if row is None:
        return None
    return RepoWorkspace(
        repo_id=row.repo_id,
        branch=row.branch,
        local_path=row.local_path,
        last_synced_commit=row.last_synced_commit,
        last_requested_at=row.last_requested_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
