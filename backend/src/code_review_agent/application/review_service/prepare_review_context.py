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
    """Return the DB-resolved repo_root (local_path), raising on bad input.

    ``branch`` selects a per-branch workspace row (Branch-Aware addendum §5);
    when None, the default-branch (base-clone) row is used, preserving Phase 1
    semantics for the plain graph_commit_hash path. The use-case is pure and
    side-effect-free — it never triggers a build; the route does that.
    """

    def __init__(
        self,
        workspace_query: RepoWorkspaceQueryPort,
        readiness: GraphReadinessPort,
    ) -> None:
        self._workspace_query = workspace_query
        self._readiness = readiness

    def execute(
        self, repo_id: str, graph_commit_hash: str, branch: str | None = None
    ) -> str:
        if not self._workspace_query.repo_is_registered(repo_id):
            raise RepoNotFoundError(repo_id)

        if branch is not None:
            workspace = self._workspace_query.get_by_repo_id_and_branch(repo_id, branch)
        else:
            workspace = self._workspace_query.get_by_repo_id(repo_id)

        if workspace is None or workspace.last_synced_commit != graph_commit_hash:
            raise GraphNotReadyError(repo_id, graph_commit_hash)

        if not self._readiness.is_ready(repo_id, graph_commit_hash):
            raise GraphNotReadyError(repo_id, graph_commit_hash)

        return workspace.local_path
