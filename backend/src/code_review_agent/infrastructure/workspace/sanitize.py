import re


def sanitize_repo_id(repo_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", repo_id)
    return safe.strip("_").lower() or "repo"
