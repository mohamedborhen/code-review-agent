from typing import Protocol


class RepoSourcePort(Protocol):
    def clone(self, repo_url: str, local_path: str) -> str:
        ...

    def sync(self, local_path: str, ref: str) -> str:
        ...

    def create_worktree(self, base_repo_path: str, branch: str, target_path: str) -> str:
        """Check out ``branch`` into a new worktree at ``target_path`` sharing the
        base clone's object database. Returns the checked-out commit SHA."""
        ...

    def update_worktree(self, worktree_path: str, branch: str) -> str:
        """Fast-forward an existing worktree to the latest commit of ``branch``.
        Returns the new HEAD commit SHA."""
        ...

    def current_branch(self, local_path: str) -> str:
        """Return the checked-out branch at ``local_path`` (default branch when
        HEAD is detached). Empty string if it cannot be determined."""
        ...
