"""Compliance subagent runtime: builds the deepagents SubAgent dict."""

from typing import Any

from infrastructure.agents_runtime.capture import CaptureStore, SubagentCaptureMiddleware
from infrastructure.agents_runtime.memory_tools import (
    build_private_memory_tools,
    build_shared_memory_tools,
)
from infrastructure.agents_runtime.tool_scoping import load_prompt, scope_agent_tools


async def build_compliance_spec(
    mcp_client,
    store: CaptureStore | None = None,
    review_session_id: int | None = None,
    tool_call_repo: Any | None = None,
) -> dict:
    spec: dict = {
        "name": "compliance",
        "description": "Checks a diff against team coding standards and Jira ticket scope",
        "system_prompt": load_prompt("compliance"),
        "tools": (
            await scope_agent_tools(mcp_client, "compliance", store, review_session_id, tool_call_repo)
            + build_shared_memory_tools()
            + build_private_memory_tools("compliance")
        ),
    }
    if store is not None:
        spec["middleware"] = [SubagentCaptureMiddleware("compliance", store)]
    return spec
