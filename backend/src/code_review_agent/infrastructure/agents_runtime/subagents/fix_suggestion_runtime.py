"""Fix Suggestion subagent runtime: builds the deepagents SubAgent dict.

Has refactor_tool (preview) but NEVER apply_refactor_tool �?" see AGENTS.md
Safety & Correctness Rules.
"""

from infrastructure.agents_runtime.capture import CaptureStore, SubagentCaptureMiddleware
from infrastructure.agents_runtime.tool_scoping import load_prompt, scope_agent_tools


async def build_fix_suggestion_spec(mcp_client, store: CaptureStore | None = None) -> dict:
    spec: dict = {
        "name": "fix_suggestion",
        "description": "Proposes concrete, grounded fixes for review findings (never applies them)",
        "system_prompt": load_prompt("fix_suggestion"),
        "tools": await scope_agent_tools(mcp_client, "fix_suggestion"),
    }
    if store is not None:
        spec["middleware"] = [SubagentCaptureMiddleware("fix_suggestion", store)]
    return spec
