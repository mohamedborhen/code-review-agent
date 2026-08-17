"""Application-layer service that creates/updates a branch worktree and its graph.

Dispatched from the POST /review route as a background task when a review is
requested for a (repo_id, branch) whose graph isn't ready yet (Branch-Aware
addendum §5). Same shape as CloneRepositoryService / SyncOnWebhookService: a
class with a sync ``execute()`` that orchestrates RepoSourcePort worktree ops
and GraphBuilderPort build/update, persists the resulting commit/status, and
releases the per-branch lock in a ``finally`` block.

``repo_source`` and ``graph_builder`` are injected ports; persistence goes
through the injected ``workspace_store`` so this Layer-3 service never touches
SQL directly (matching the port/adapter split of the review pre-flight).
"""

import logging
from typing import Protocol

from domain.graph.graph_builder_port import GraphBuilderPort
from domain.entities.repo_workspace import RepoWorkspace
from domain.repo.repo_source_port import RepoSourcePort

logger = logging.getLogger(__name__)


class WorkspaceStore(Protocol):
    """Persistence the ensure flow needs — implemented by the SQLModel
    repository adapter. Reads mirror RepoWorkspaceQueryPort; writes are used
    only from this background flow (never from the review pre-flight)."""

    def get_by_repo_id(self, repo_id: str) -> RepoWorkspace | None: ...
    def get_by_repo_id_and_branch(self, repo_id: str, branch: str) -> RepoWorkspace | None: ...
    def add_worktree_row(self, repo_id: str, branch: str, local_path: str, last_synced_commit: str) -> None: ...
    def update_synced_commit(self, repo_id: str, branch: str, last_synced_commit: str) -> None: ...
    def record_graph_snapshot(self, repo_id: str, commit_hash: str, status: str, error_message: str | None) -> None: ...


class EnsureBranchWorktreeService:
    def __init__(
        self,
        repo_source: RepoSourcePort,
        graph_builder: GraphBuilderPort,
        workspace_store: WorkspaceStore,
        workspace_root: str,
        acquire_lock,
    ) -> None:
        self._repo_source = repo_source
        self._graph_builder = graph_builder
        self._store = workspace_store
        self._workspace_root = workspace_root
        self._acquire_lock = acquire_lock

    def execute(self, repo_id: str, branch: str, resolved_commit: str) -> None:
        base = self._store.get_by_repo_id(repo_id)
        if base is None:
            logger.error("ensure worktree: no base clone for repo %s", repo_id)
            self._store.record_graph_snapshot(repo_id, resolved_commit, "error", "no base clone")
            return

        lock = self._acquire_lock(self._workspace_root, repo_id, branch)
        with lock:
            self._build_or_update(repo_id, branch, base, resolved_commit)

    def _build_or_update(
        self, repo_id: str, branch: str, base: RepoWorkspace, resolved_commit: str
    ) -> None:
        existing = self._store.get_by_repo_id_and_branch(repo_id, branch)

        if existing is None:
            worktree_path = _resolve_worktree_path(self._workspace_root, repo_id, branch)
            try:
                checked_out = self._repo_source.create_worktree(
                    base.local_path, branch, worktree_path
                )
            except Exception as e:
                logger.error("create worktree %s/%s failed: %s", repo_id, branch, e)
                self._store.record_graph_snapshot(repo_id, resolved_commit, "error", str(e))
                return

            self._store.add_worktree_row(repo_id, branch, worktree_path, checked_out)

            status = self._graph_builder.build(repo_root=worktree_path)
            self._finish(repo_id, branch, checked_out, status)
            return

        # Existing worktree — fast-forward to the branch tip, then incremental update.
        try:
            checked_out = self._repo_source.update_worktree(existing.local_path, branch)
        except Exception as e:
            logger.error("update worktree %s/%s failed: %s", repo_id, branch, e)
            self._store.record_graph_snapshot(repo_id, resolved_commit, "error", str(e))
            return

        base_commit = existing.last_synced_commit or "HEAD~1"
        status = self._graph_builder.update(
            repo_root=existing.local_path, base=base_commit
        )

        # Force-push safety (§3): if the diff base is no longer reachable, the
        # CRG adapter returns an error status; fall back to a full rebuild.
        if status.status != "ready":
            logger.warning(
                "incremental update for %s/%s not ready (%s); falling back to full rebuild",
                repo_id,
                branch,
                status.error_message,
            )
            status = self._graph_builder.build(repo_root=existing.local_path)

        self._finish(repo_id, branch, checked_out, status)

    def _finish(self, repo_id: str, branch: str, commit: str, status) -> None:
        if status.status == "ready":
            self._store.update_synced_commit(repo_id, branch, commit)
            self._store.record_graph_snapshot(repo_id, commit, "ready", None)
        else:
            self._store.record_graph_snapshot(
                repo_id, commit, status.status, status.error_message
            )


def _resolve_worktree_path(workspace_root: str, repo_id: str, branch: str) -> str:
    from infrastructure.workspace.workspace_path_resolver import resolve_worktree_path
    return resolve_worktree_path(workspace_root, repo_id, branch)