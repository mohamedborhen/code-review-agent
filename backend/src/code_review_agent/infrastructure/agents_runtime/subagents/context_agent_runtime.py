"""Context Agent runtime (Phase 3): read-only conversation recall.

Granted ONLY the ``search_messages`` tool (PHASE_3.md §6, AGENTS.md). Unlike the
Phase 2 specialist subagents this is not a deepagents SubAgent dict — context
recall is a single deterministic tool call, so the "runtime" here is the
scoped-tool accessor the orchestrator uses. The Context Agent never writes: no
write tool exists anywhere in its path, and it is strictly a historical-
conversation retrieval component (no shared/private memory, no summarization).
"""

import asyncio
import json
import logging
import time

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict

from infrastructure.agents_runtime.tool_scoping import _strip_null_unions, scope_agent_tools
from infrastructure.agents_runtime.utils import extract_text as _extract_text
from infrastructure.mcp_clients.mcp_client_factory import scoped

logger = logging.getLogger(__name__)


class ContextSearchQuery(BaseModel):
    """LLM-visible args for the audited context tool (PHASE_3.md §9.5).

    Deliberately exposes ONLY ``query``/``limit``/``exclude_message_id``.
    Identity (conversation_id/user_id/repo_id) is closure-bound at construction
    time and never appears here — ``extra="forbid"`` makes the schema the
    security boundary: a hostile/injected call that supplies identity keys is
    REJECTED at validation (pydantic ``ValidationError``), never silently
    overridden downstream. ``model_json_schema`` is overridden to strip
    anyOf-null unions (mirrors ``tool_scoping._with_clean_schema``) so the
    LLM-facing schema stays clean.
    """

    model_config = ConfigDict(extra="forbid")

    query: str
    limit: int = 10
    exclude_message_id: int | None = None

    @classmethod
    def model_json_schema(cls, *args, **kwargs):
        return _strip_null_unions(super().model_json_schema(*args, **kwargs))


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


async def get_audited_context_tool(
    mcp_client,
    *,
    conversation_id: int,
    user_id: str,
    repo_id: str,
    audit,
    review_session_id: int | None,
    store=None,
    tool_call_repo=None,
):
    """Build the Context Agent tool granted to the orchestrator root agent.

    Chains the event-wrapped scoped ``search_messages`` tool (timeline capture
    via ``scope_agent_tools``) with an audit wrapper that records one
    AgentExecution row per invocation through the injected ConversationAuditPort
    (query/counts/status only — never message content or snippets).

    Identity security (PHASE_3.md §9.5): ``conversation_id``/``user_id``/
    ``repo_id`` are closure-bound at construction time — the LLM never supplies
    them. The tool's ``args_schema`` is ``ContextSearchQuery``, which exposes
    only query/limit/exclude_message_id and forbids extra keys, so any hostile
    call that tries to pass identity is rejected at schema validation before
    the underlying tool runs. The correct values are injected here, server-side.

    Returns None when the tool is unavailable (server down / not registered) so
    the caller can skip recall without failing the review.
    """
    try:
        tools = await scope_agent_tools(
            mcp_client, "context_agent", store, review_session_id, tool_call_repo
        )
    except Exception as exc:
        logger.warning(
            "Context recall skipped: scope_agent_tools failed (%s)",
            type(exc).__name__,
        )
        return None
    if not tools:
        return None
    tool = tools[0]

    async def _audited(**kwargs: object) -> object:
        started = time.monotonic()
        # Identity is closure-bound, never LLM-supplied. ContextSearchQuery's
        # extra="forbid" guarantees kwargs cannot carry identity keys, so these
        # injections are authoritative, not a merge.
        kwargs["conversation_id"] = conversation_id
        kwargs["user_id"] = user_id
        kwargs["repo_id"] = repo_id
        raw = await tool.ainvoke(kwargs)
        latency_ms = int((time.monotonic() - started) * 1000)
        text = _extract_text(raw)
        results_count = 0
        status = "ok"
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                results_count = len(payload.get("results", []) or [])
                status = payload.get("error") or "ok"
        except (TypeError, ValueError):
            status = "invalid_response"
        await asyncio.to_thread(
            audit.record_context_invocation,
            conversation_id,
            str(kwargs.get("query", "")),
            results_count,
            latency_ms,
            status,
            review_session_id,
        )
        return text

    return StructuredTool.from_function(
        coroutine=_audited,
        name=tool.name,
        description=tool.description,
        args_schema=ContextSearchQuery,
        handle_tool_error=tool.handle_tool_error,
        return_direct=tool.return_direct,
    )


async def search_conversation_context(
    mcp_client,
    *,
    conversation_id: int,
    user_id: str,
    repo_id: str,
    query: str,
    limit: int = 10,
    exclude_message_id: int | None = None,
) -> str | None:
    """Invoke search_messages with explicit typed identity params.

    Returns the raw JSON string from the tool (or None when the tool is
    unavailable). Identity is passed as parameters — never derived from MCP
    headers (PHASE_3.md §5, §9.5). Caller owns parsing + audit logging.
    ``exclude_message_id`` optionally excludes one message from the results.
    """
    tool = await get_search_messages_tool(mcp_client)
    if tool is None:
        return None
    kwargs: dict[str, object] = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "repo_id": repo_id,
        "query": query,
        "limit": limit,
    }
    if exclude_message_id is not None:
        kwargs["exclude_message_id"] = exclude_message_id
    result = await tool.ainvoke(kwargs)
    return _extract_text(result)