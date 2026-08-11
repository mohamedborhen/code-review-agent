"""Pre-flight use-case: graph readiness + workspace path resolution.

This is the documented, blessed exception to Phase 2's async layer — the
route calls this *synchronous* use-case from inside the async POST /review
handler. It wraps two Phase 1 synchronous services (GraphReadinessService +
a RepoWorkspace lookup) behind injected ports. See AGENTS.md's async/sync
boundary section. Do not spread this pattern elsewhere.
"""

from application.review_service.errors import GraphNotReadyError, RepoNotFoundError
from domain.review.review_context_ports import GraphReadinessPort, RepoWorkspaceQueryPort


class PrepareReviewContextService:
    """Return the DB-resolved repo_root (local_path), raising on bad input."""

    def __init__(
        self,
        workspace_query: RepoWorkspaceQueryPort,
        readiness: GraphReadinessPort,
    ) -> None:
        self._workspace_query = workspace_query
        self._readiness = readiness

    def execute(self, repo_id: str, graph_commit_hash: str) -> str:
        workspace = self._workspace_query.get_by_repo_id(repo_id)
        if workspace is None:
            raise RepoNotFoundError(repo_id)

        if not self._readiness.is_ready(repo_id, graph_commit_hash):
            raise GraphNotReadyError(repo_id, graph_commit_hash)

        return workspace.local_path
