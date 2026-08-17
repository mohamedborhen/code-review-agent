import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from sqlmodel import Session, select

from infrastructure.db.engine import engine
from infrastructure.db.models import RepoWorkspace
from infrastructure.workspace.workspace_path_resolver import sanitize_repo_id

logger = logging.getLogger(__name__)


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
            # Worktree-aware LRU: last_requested_at is the recency signal for the
            # per-branch rows (Branch-Aware addendum §11), falling back to
            # updated_at for legacy rows where it is NULL. One row per branch, so
            # a per-branch row eviction removes exactly one worktree.
            statement = select(RepoWorkspace).order_by(RepoWorkspace.last_requested_at.asc())
            workspaces = session.exec(statement).all()
            workspaces.sort(
                key=lambda ws: (ws.last_requested_at or ws.updated_at)
            )

            for ws in workspaces:
                if self._get_workspace_size() <= self._max_bytes:
                    break
                ws_path = Path(ws.local_path)
                # Prefer `git worktree remove` for worktrees so the base clone's
                # .git/worktrees metadata is cleaned; fall back to rmtree for a
                # base clone (which has no such entry). A worktree's local_path
                # lives under the base clone's dir, so detect it via the git
                # worktree list from the base clone path.
                base = self._find_base_clone(ws.repo_id, ws_path)
                if base is not None and self._is_worktree(base, ws_path):
                    self._git_worktree_remove(base, ws_path)
                elif ws_path.exists():
                    shutil.rmtree(ws_path, ignore_errors=True)
                session.delete(ws)
                evicted.append(f"{ws.repo_id}@{ws.branch}")
                session.commit()

        return evicted

    def _find_base_clone(self, repo_id: str, ws_path: Path) -> Path | None:
        """Resolve the base clone for this repo deterministically.

        A worktree is a sibling of the base clone (``{root}/{safe_id}`` vs
        ``{root}/{safe_id}__{branch}``), so walking up from the worktree path
        can never reach it — and a worktree's ``.git`` is a file, not a
        directory, so the old walk returned the worktree as its own "base",
        causing eviction to ``rmtree`` it and leave stale ``.git/worktrees``
        metadata. ``ws_path`` is kept for call-site compatibility but is no
        longer needed to find the base.
        """
        base = self._workspace_root / sanitize_repo_id(repo_id)
        if (base / ".git").is_dir():
            return base
        return None

    @staticmethod
    def _is_worktree(base: Path, ws_path: Path) -> bool:
        if ws_path == base:
            return False
        try:
            result = subprocess.run(
                ["git", "-C", str(base), "worktree", "list", "--porcelain"],
                capture_output=True, text=True,
            )
        except Exception:
            return False
        return f"worktree {ws_path}".replace("\\", "/") in result.stdout.replace("\\", "/")

    @staticmethod
    def _git_worktree_remove(base: Path, ws_path: Path) -> None:
        subprocess.run(
            ["git", "-C", str(base), "worktree", "remove", "--force", str(ws_path)],
            capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "-C", str(base), "worktree", "prune"],
            capture_output=True, text=True,
        )

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