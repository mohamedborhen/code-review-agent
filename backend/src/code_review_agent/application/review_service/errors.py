"""Application-layer exceptions for the review use-cases.

These carry the *outcome* of a use-case, not an HTTP concern — the Layer 2
route translates them to HTTP status codes. Keeping them framework-free lets
the Application layer import nothing from FastAPI (Layer 3 clean).
"""


class RepoNotFoundError(Exception):
    """The repo_id has no RepoWorkspace row (caller responds 404)."""

    def __init__(self, repo_id: str) -> None:
        self.repo_id = repo_id
        super().__init__(f"Unknown repo_id: {repo_id}")


class GraphNotReadyError(Exception):
    """The graph isn't ready for this exact commit (caller responds 425)."""

    def __init__(self, repo_id: str, commit_hash: str) -> None:
        self.repo_id = repo_id
        self.commit_hash = commit_hash
        super().__init__(f"Graph not ready for {commit_hash} in {repo_id}")


class UnknownRequestTypeError(Exception):
    """The request_type has no routing-policy entry (caller responds 400)."""

    def __init__(self, request_type: str) -> None:
        self.request_type = request_type
        super().__init__(f"Unknown request_type: {request_type}")
