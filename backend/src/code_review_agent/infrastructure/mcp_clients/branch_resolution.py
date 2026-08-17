"""Layer 5 adapter: resolve a GitHub branch name to its current commit SHA.

Calls the GitHub MCP server's ``list_branches`` tool via the shared
``MultiServerMCPClient`` held on ``app.state`` — never a new client per
request (PHASE_2.md). Tool access is read-only by construction (server-side
``X-MCP-Readonly`` + scoped ``X-MCP-Toolsets``) and here additionally reduced
to the single ``list_branches`` tool via the existing ``scoped()`` helper —
the full registry list is never handed to any agent (AGENTS.md).

Response shape verified against the live server (Branch-Aware addendum §4):
``[{name, sha, protected}]``.
"""

import json
from typing import Any

from infrastructure.mcp_clients.mcp_client_factory import scoped


class BranchNotFoundError(Exception):
    """The requested branch is not present on the remote (caller responds 404)."""

    def __init__(self, owner: str, repo: str, branch: str) -> None:
        self.owner = owner
        self.repo = repo
        self.branch = branch
        super().__init__(f"Branch {branch!r} not found in {owner}/{repo}")


async def list_repo_branches(mcp_client, owner: str, repo: str) -> list[dict[str, Any]]:
    """Return ``[{name, sha, protected}, ...]`` for every remote branch."""
    github_tools = await mcp_client.get_tools(server_name="github")
    list_branches_tool = scoped(github_tools, {"list_branches"})[0]
    result = await list_branches_tool.ainvoke({"owner": owner, "repo": repo})
    text = _extract_text(result)
    if not text:
        return []
    payload = json.loads(text) if isinstance(text, str) else text
    if isinstance(payload, dict) and isinstance(payload.get("branches"), list):
        return payload["branches"]
    if isinstance(payload, list):
        return payload
    raise BranchNotFoundError(owner, repo, "<all>")


async def resolve_branch_to_commit(
    mcp_client, owner: str, repo: str, branch: str
) -> str:
    """Resolve ``branch`` to its current commit SHA via ``list_branches``."""
    branches = await list_repo_branches(mcp_client, owner, repo)
    for entry in branches:
        if entry.get("name") == branch:
            sha = entry.get("sha")
            if sha:
                return sha
            raise BranchNotFoundError(owner, repo, branch)
    raise BranchNotFoundError(owner, repo, branch)


def _extract_text(result: Any) -> str:
    """Pull the text payload out of a langchain tool result.

    The GitHub MCP tool returns ``list[dict]`` content items with a ``text``
    key (and possibly ``structuredContent``); ``str`` or plain objects are
    returned as-is.
    """
    if isinstance(result, str):
        return result
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                parts.append(item["text"])
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else json.dumps(content)
    return str(content or "")
