"""Performance subagent runtime: builds the deepagents SubAgent dict."""

from infrastructure.agents_runtime.capture import CaptureStore, SubagentCaptureMiddleware
from infrastructure.agents_runtime.tool_scoping import load_prompt, scope_agent_tools


async def build_performance_spec(mcp_client, store: CaptureStore | None = None) -> dict:
    spec: dict = {
        "name": "performance",
        "description": "Determines whether a change risks a performance regression",
        "system_prompt": load_prompt("performance"),
        "tools": await scope_agent_tools(mcp_client, "performance"),
    }
    if store is not None:
        spec["middleware"] = [SubagentCaptureMiddleware("performance", store)]
    return spec
