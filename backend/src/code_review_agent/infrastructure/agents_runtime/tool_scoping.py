"""Shared tool-scoping + prompt loading for the agents_runtime package."""

import time
from pathlib import Path

from langchain_core.tools import BaseTool, StructuredTool

from infrastructure.agents_runtime.tool_lists import AGENT_TOOL_PLAN
from infrastructure.event_bus.log_event_bus import log_event
from infrastructure.mcp_clients.mcp_client_factory import scoped

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a system prompt from prompts/<name>.md."""
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _truncate(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def _wrap_with_events(tool: BaseTool, agent_name: str) -> BaseTool:
    """Wrap a scoped MCP tool so its call/result reach the event bus.

    Subagent-internal MCP calls are invisible to the orchestrator's message walk
    (deepagents nests them inside the subagent graph), so without this wrapper
    the event log cannot prove e.g. that Compliance actually called
    ``jira_get_issue`` / ``confluence_get_page``. The wrapper keeps the tool's
    exact name/schema so the model sees no difference.
    """
    if not isinstance(tool, StructuredTool):
        return tool

    async def _wrapped(**kwargs: object) -> object:
        await log_event(
            "tool_call",
            agent=agent_name,
            tool=tool.name,
            input_=_truncate(str(kwargs)),
        )
        start = time.monotonic()
        try:
            result = await tool.ainvoke(kwargs)
        except Exception as exc:
            await log_event(
                "tool_result",
                agent=agent_name,
                tool=tool.name,
                output=f"ERROR {type(exc).__name__}: {exc}",
            )
            raise
        await log_event(
            "tool_result",
            agent=agent_name,
            tool=tool.name,
            output=_truncate(str(result)),
        )
        return result

    return StructuredTool.from_function(
        coroutine=_wrapped,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        handle_tool_error=tool.handle_tool_error,
        return_direct=tool.return_direct,
    )


async def scope_agent_tools(mcp_client, agent_name: str) -> list[BaseTool]:
    """Fetch tools from the shared client and scope them to the agent's plan."""
    plan = AGENT_TOOL_PLAN[agent_name]
    tools: list[BaseTool] = []
    for server_name, allowed in plan.items():
        if allowed == set():
            continue
        server_tools = await mcp_client.get_tools(server_name=server_name)
        if allowed is None:
            tools.extend(_wrap_with_events(t, agent_name) for t in server_tools)
            continue
        tools.extend(_wrap_with_events(t, agent_name) for t in scoped(server_tools, allowed))
    return tools
