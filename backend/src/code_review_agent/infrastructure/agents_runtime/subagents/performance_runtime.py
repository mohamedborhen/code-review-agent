"""Performance subagent runtime: builds the deepagents SubAgent dict."""

from infrastructure.agents_runtime.capture import CaptureStore, SubagentCaptureMiddleware
from infrastructure.agents_runtime.memory_tools import (
    build_private_memory_tools,
    build_shared_memory_tools,
)
from infrastructure.agents_runtime.tool_scoping import load_prompt, scope_agent_tools


async def build_performance_spec(mcp_client, store: CaptureStore | None = None) -> dict:
    spec: dict = {
        "name": "performance",
        "description": "Determines whether a change risks a performance regression",
        "system_prompt": load_prompt("performance"),
        "tools": (
            await scope_agent_tools(mcp_client, "performance", store)
            + build_shared_memory_tools()
            + build_private_memory_tools("performance")
        ),
    }
    if store is not None:
        spec["middleware"] = [SubagentCaptureMiddleware("performance", store)]
    return spec
