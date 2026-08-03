"""Regression subagent runtime: builds the deepagents SubAgent dict."""

from infrastructure.agents_runtime.capture import CaptureStore, SubagentCaptureMiddleware
from infrastructure.agents_runtime.tool_scoping import load_prompt, scope_agent_tools


async def build_regression_spec(mcp_client, store: CaptureStore | None = None) -> dict:
    spec: dict = {
        "name": "regression",
        "description": "Identifies blast radius and untested hotspots of a change",
        "system_prompt": load_prompt("regression"),
        "tools": await scope_agent_tools(mcp_client, "regression"),
    }
    if store is not None:
        spec["middleware"] = [SubagentCaptureMiddleware("regression", store)]
    return spec
