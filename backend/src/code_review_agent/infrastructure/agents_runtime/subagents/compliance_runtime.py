"""Compliance subagent runtime: builds the deepagents SubAgent dict."""

from infrastructure.agents_runtime.capture import CaptureStore, SubagentCaptureMiddleware
from infrastructure.agents_runtime.tool_scoping import load_prompt, scope_agent_tools


async def build_compliance_spec(mcp_client, store: CaptureStore | None = None) -> dict:
    spec: dict = {
        "name": "compliance",
        "description": "Checks a diff against team coding standards and Jira ticket scope",
        "system_prompt": load_prompt("compliance"),
        "tools": await scope_agent_tools(mcp_client, "compliance"),
    }
    if store is not None:
        spec["middleware"] = [SubagentCaptureMiddleware("compliance", store)]
    return spec
