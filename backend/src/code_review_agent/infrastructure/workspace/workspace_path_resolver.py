import re


def sanitize_repo_id(repo_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", repo_id)
    return safe.strip("_").lower() or "repo"


def resolve_workspace_path(workspace_root: str, repo_id: str) -> str:
    safe_id = sanitize_repo_id(repo_id)
    return f"{workspace_root.rstrip('/')}/{safe_id}"


def resolve_worktree_path(workspace_root: str, repo_id: str, branch: str) -> str:
    """Return the worktree directory for ``(repo_id, branch)``.

    A sibling of the base clone (never nested inside it, which would pollute
    the base clone's working tree), still inside ``WORKSPACE_ROOT`` so the CRG
    server container sees it (§12). Mirrors the §8 lock-key scheme.
    """
    safe_id = sanitize_repo_id(repo_id)
    safe_branch = sanitize_repo_id(branch)
    return f"{workspace_root.rstrip('/')}/{safe_id}__{safe_branch}"
