"""Layer 4 ports for pre-flight review-context preparation.

The review route's pre-flight step needs two lookups before any agent runs:
the workspace row (for the DB-resolved ``repo_root``) and graph readiness (so
subagents never run against a graph that isn't ready for this exact commit).
Both are declared here as Protocols so the use-case depends only on domain
shapes, never on Infrastructure classes. Implemented by Layer 5.
"""

from typing import Protocol

from domain.entities.repo_workspace import RepoWorkspace


class RepoWorkspaceQueryPort(Protocol):
    def get_by_repo_id(self, repo_id: str) -> RepoWorkspace | None:
        """Return the workspace row for ``repo_id``, or None if untracked."""
        ...


class GraphReadinessPort(Protocol):
    def is_ready(self, repo_id: str, commit_hash: str) -> bool:
        """True only when the graph for this exact commit is built and ready."""
        ...
