import re


def sanitize_repo_id(repo_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", repo_id)
    return safe.strip("_").lower() or "repo"


def resolve_workspace_path(workspace_root: str, repo_id: str) -> str:
    safe_id = sanitize_repo_id(repo_id)
    return f"{workspace_root.rstrip('/')}/{safe_id}"
