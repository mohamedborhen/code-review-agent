"""Shared tool-scoping + prompt loading for the agents_runtime package."""

import time
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from infrastructure.agents_runtime.capture import CaptureStore
from infrastructure.agents_runtime.tool_descriptions import TOOL_DESCRIPTION_OVERRIDES
from infrastructure.agents_runtime.tool_lists import AGENT_TOOL_PLAN
from infrastructure.event_bus.log_event_bus import log_event
from infrastructure.mcp_clients.mcp_client_factory import scoped

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a system prompt from prompts/<name>.md."""
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _truncate(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


# Cap on the tool result that is fed BACK to the model. CRG calls
# (get_review_context_tool with include_source, detect_changes_tool, ...) can
# return tens of kilobytes of JSON; once returned, it sits in the conversation
# history and is re-sent on every subsequent turn, compounding the token cost.
# The event log keeps its own tighter cap (_truncate above); this one is what
# the model actually sees.
_TOOL_RESULT_MAX_CHARS = 4000


def _truncate_result(result: object) -> object:
    if isinstance(result, str):
        return _truncate(result, _TOOL_RESULT_MAX_CHARS)
    text = str(result)
    if len(text) <= _TOOL_RESULT_MAX_CHARS:
        return result
    return text[:_TOOL_RESULT_MAX_CHARS] + "...(truncated)"


def _is_null_schema(node: object) -> bool:
    return isinstance(node, dict) and node.get("type") == "null"


def _strip_null_unions(node: Any) -> Any:
    """Recursively remove ``{"type": "null"}`` branches from ``anyOf``.

    OpenAI-style strict tool-call validation rejects schemas where an optional
    parameter serializes as ``anyOf: [X, {"type": "null"}]`` even when the call
    itself is valid. Optional MCP parameters generate exactly this shape, so the
    null branch is stripped. A single-element ``anyOf`` is unwrapped, merging
    sibling keys (titles, defaults, descriptions) into the surviving member so
    the schema keeps its original meaning.
    """
    if isinstance(node, list):
        return [_strip_null_unions(item) for item in node]
    if not isinstance(node, dict):
        return node

    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key == "anyOf":
            members = [_strip_null_unions(item) for item in value]
            members = [item for item in members if not _is_null_schema(item)]
            if not members:
                cleaned[key] = [{"type": "null"}]
            elif len(members) == 1 and isinstance(members[0], dict):
                merged = dict(members[0])
                for other_key, other_value in node.items():
                    if other_key != "anyOf":
                        merged[other_key] = _strip_null_unions(other_value)
                cleaned.update(merged)
            else:
                cleaned[key] = members
        elif isinstance(value, (dict, list)):
            cleaned[key] = _strip_null_unions(value)
        else:
            cleaned[key] = value
    return cleaned


def _with_clean_schema(schema: Any) -> Any:
    """Return a tool args schema free of ``anyOf``-null unions.

    ``StructuredTool.args_schema`` accepts either a pydantic model or a plain
    JSON-schema dict (verified against langchain-core 1.5.3), so both are
    normalized to a cleaned dict — no model rebuild needed.
    """
    if isinstance(schema, dict):
        return _strip_null_unions(schema)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return _strip_null_unions(schema.model_json_schema())
    return schema


def _wrap_with_events(tool: BaseTool, agent_name: str, store: CaptureStore | None = None) -> BaseTool:
    """Wrap a scoped MCP tool so its call/result reach the event bus.

    Subagent-internal MCP calls are invisible to the orchestrator's message walk
    (deepagents nests them inside the subagent graph), so without this wrapper
    the event log cannot prove e.g. that Compliance actually called
    ``jira_get_issue`` / ``confluence_get_page``. The wrapper keeps the tool's
    exact name/schema so the model sees no difference. Each executed call is
    also timed into the shared ``CaptureStore`` so the latency timeline includes
    per-tool durations.
    """
    if not isinstance(tool, StructuredTool):
        return tool

    async def _wrapped(**kwargs: object) -> object:
        ts = int(time.time() * 1000)
        await log_event(
            "tool_call",
            agent=agent_name,
            tool=tool.name,
            input_=_truncate(str(kwargs)),
            ts=ts,
        )
        start = time.monotonic()
        try:
            result = await tool.ainvoke(kwargs)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            if store is not None:
                store.record_call(agent_name, "tool", tool.name, duration_ms)
            await log_event(
                "tool_result",
                agent=agent_name,
                tool=tool.name,
                output=f"ERROR {type(exc).__name__}: {exc}",
                ts=ts,
                duration_ms=duration_ms,
            )
            raise
        duration_ms = int((time.monotonic() - start) * 1000)
        if store is not None:
            store.record_call(agent_name, "tool", tool.name, duration_ms)
        await log_event(
            "tool_result",
            agent=agent_name,
            tool=tool.name,
            output=_truncate(str(result)),
            ts=ts,
            duration_ms=duration_ms,
        )
        return _truncate_result(result)

    return StructuredTool.from_function(
        coroutine=_wrapped,
        name=tool.name,
        description=TOOL_DESCRIPTION_OVERRIDES.get(tool.name, tool.description),
        args_schema=_with_clean_schema(tool.args_schema),
        handle_tool_error=tool.handle_tool_error,
        return_direct=tool.return_direct,
    )


async def scope_agent_tools(mcp_client, agent_name: str, store: CaptureStore | None = None) -> list[BaseTool]:
    """Fetch tools from the shared client and scope them to the agent's plan."""
    plan = AGENT_TOOL_PLAN[agent_name]
    tools: list[BaseTool] = []
    for server_name, allowed in plan.items():
        if allowed == set():
            continue
        server_tools = await mcp_client.get_tools(server_name=server_name)
        if allowed is None:
            tools.extend(_wrap_with_events(t, agent_name, store) for t in server_tools)
            continue
        tools.extend(_wrap_with_events(t, agent_name, store) for t in scoped(server_tools, allowed))
    return tools
