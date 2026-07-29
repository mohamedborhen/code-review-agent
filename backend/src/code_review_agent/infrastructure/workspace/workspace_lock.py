import os
import re

from filelock import FileLock


def sanitize_repo_id(repo_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", repo_id)
    return safe.strip("_").lower() or "repo"


def acquire_workspace_lock(workspace_root: str, repo_id: str) -> FileLock:
    safe = sanitize_repo_id(repo_id)
    workspace_dir = f"{workspace_root.rstrip('/')}/{safe}"
    os.makedirs(workspace_dir, exist_ok=True)
    return FileLock(f"{workspace_root.rstrip('/')}/.{safe}.lock", timeout=5)
