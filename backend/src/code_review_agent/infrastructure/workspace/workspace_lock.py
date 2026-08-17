import os
import re

from filelock import FileLock, Timeout


def sanitize_repo_id(repo_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", repo_id)
    return safe.strip("_").lower() or "repo"


def acquire_workspace_lock(
    workspace_root: str, repo_id: str, branch: str | None = None
) -> FileLock:
    """Return a per-repo (or per-branch) FileLock, not yet acquired.

    Lock scope moved from ``repo_id`` to ``(repo_id, branch)`` by the
    Branch-Aware addendum (§8). ``branch=None`` keeps the Phase 1 hidden-dot
    default-branch key (``.{safe}.lock``) so the existing registration call
    site stays valid; a branch lock uses ``.{safe}_{safe_branch}.lock`` in
    ``workspace_root`` (never inside the worktree dir, which may not exist yet).
    """
    safe = sanitize_repo_id(repo_id)
    if branch is None:
        workspace_dir = f"{workspace_root.rstrip('/')}/{safe}"
        os.makedirs(workspace_dir, exist_ok=True)
        return FileLock(f"{workspace_root.rstrip('/')}/.{safe}.lock", timeout=5)
    os.makedirs(workspace_root, exist_ok=True)
    safe_branch = sanitize_repo_id(branch)
    return FileLock(f"{workspace_root.rstrip('/')}/.{safe}_{safe_branch}.lock", timeout=5)


def try_acquire_lock(workspace_root: str, repo_id: str, branch: str) -> bool:
    """Non-blocking probe for the per-branch lock.

    Returns True when the lock is immediately free and False when another
    request is already building this branch (filelock.Timeout at timeout=0).
    It is a probe only: the acquiring background task re-acquires the same
    lock blocking and releases it in a finally block.
    """
    lock = acquire_workspace_lock(workspace_root, repo_id, branch)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return False
    lock.release()
    return True
