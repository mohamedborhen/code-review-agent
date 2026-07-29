import os
import shutil
import time
from pathlib import Path

from sqlmodel import Session, select

from infrastructure.db.engine import engine
from infrastructure.db.models import RepoWorkspace


class WorkspaceEvictionService:
    def __init__(self, workspace_root: str, max_gb: float = 10.0) -> None:
        self._workspace_root = Path(workspace_root)
        self._max_bytes = int(max_gb * 1024 ** 3)

    def evict_if_needed(self) -> list[str]:
        total = self._get_workspace_size()
        if total <= self._max_bytes:
            return []

        evicted: list[str] = []
        with Session(engine) as session:
            statement = select(RepoWorkspace).order_by(RepoWorkspace.updated_at.asc())
            workspaces = session.exec(statement).all()

            for ws in workspaces:
                if self._get_workspace_size() <= self._max_bytes:
                    break
                ws_path = Path(ws.local_path)
                if ws_path.exists():
                    shutil.rmtree(ws_path, ignore_errors=True)
                session.delete(ws)
                evicted.append(ws.repo_id)

            session.commit()

        return evicted

    def _get_workspace_size(self) -> int:
        if not self._workspace_root.exists():
            return 0
        total = 0
        for entry in os.scandir(self._workspace_root):
            if entry.is_dir():
                total += self._dir_size(Path(entry.path))
        return total

    @staticmethod
    def _dir_size(path: Path) -> int:
        total = 0
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += WorkspaceEvictionService._dir_size(Path(entry.path))
        return total
