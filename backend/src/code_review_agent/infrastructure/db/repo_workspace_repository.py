"""SQLModel-backed adapter for RepoWorkspaceQueryPort (Layer 5).

Implements the domain port from domain/review/review_context_ports.py. The
query itself is the same Phase 1 `select(RepoWorkspace)...` the webhook flow
uses — it is only relocated here so the Application layer never touches SQL.
"""

from sqlmodel import Session, select

from domain.entities.repo_workspace import RepoWorkspace
from infrastructure.db.engine import engine
from infrastructure.db.models import RepoWorkspace as RepoWorkspaceTable


class SQLModelRepoWorkspaceRepository:
    def get_by_repo_id(self, repo_id: str) -> RepoWorkspace | None:
        with Session(engine) as session:
            statement = select(RepoWorkspaceTable).where(RepoWorkspaceTable.repo_id == repo_id)
            row = session.exec(statement).first()
        if row is None:
            return None
        return RepoWorkspace(
            repo_id=row.repo_id,
            local_path=row.local_path,
            last_synced_commit=row.last_synced_commit,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
