"""Context Agent runtime (Phase 3): read-only conversation recall.

Granted ONLY the ``search_messages`` tool (PHASE_3.md §6, AGENTS.md). Unlike the
Phase 2 specialist subagents this is not a deepagents SubAgent dict — context
recall is a single deterministic tool call made by the Application layer, so the
"runtime" here is the scoped-tool accessor the orchestrator uses. The Context
Agent never writes: no write tool exists anywhere in its path.
"""

from infrastructure.mcp_clients.mcp_client_factory import scoped


async def get_search_messages_tool(mcp_client):
    """Return the single scoped search_messages tool from the shared client.

    Explicit named tool list — never a wildcard (AGENTS.md). If the tool is
    absent (server down / not registered) the caller gets None and skips recall.
    """
    conversation_tools = await mcp_client.get_tools(server_name="conversation")
    scoped_tools = scoped(conversation_tools, {"search_messages"})
    if not scoped_tools:
        return None
    return scoped_tools[0]


async def search_conversation_context(
    mcp_client,
    *,
    conversation_id: int,
    user_id: str,
    repo_id: str,
    query: str,
    limit: int = 10,
) -> str | None:
    """Invoke search_messages with explicit typed identity params.

    Returns the raw JSON string from the tool (or None when the tool is
    unavailable). Identity is passed as parameters — never derived from MCP
    headers (PHASE_3.md §5, §9.5). Caller owns parsing + audit logging.
    """
    tool = await get_search_messages_tool(mcp_client)
    if tool is None:
        return None
    result = await tool.ainvoke(
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "repo_id": repo_id,
            "query": query,
            "limit": limit,
        }
    )
    return _extract_text(result)


def _extract_text(result) -> str:
    """Pull the text payload out of a langchain tool result (mirrors
    branch_resolution._extract_text)."""
    if isinstance(result, str):
        return result
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                parts.append(item["text"])
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else str(content)
    return str(content or "")