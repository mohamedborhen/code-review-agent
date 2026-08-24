"""Generic factory for building subagent spec dicts.

Consolidates the near-identical builder functions from the five
*_runtime.py modules into a single parameterized implementation.
"""

from typing import Any

from infrastructure.agents_runtime.capture import CaptureStore, SubagentCaptureMiddleware
from infrastructure.agents_runtime.memory_tools import (
    build_private_memory_tools,
    build_shared_memory_tools,
)
from infrastructure.agents_runtime.tool_scoping import load_prompt, scope_agent_tools

SUBAGENT_CONFIGS: dict[str, str] = {
    "compliance": "Checks a diff against team coding standards and Jira ticket scope",
    "security": "Determines whether a change introduces a security risk",
    "performance": "Determines whether a change risks a performance regression",
    "regression": "Identifies blast radius and untested hotspots of a change",
    "fix_suggestion": "Proposes concrete, grounded fixes for review findings (never applies them)",
}


async def build_subagent_spec(
    name: str,
    mcp_client: Any,
    store: CaptureStore | None = None,
    review_session_id: int | None = None,
    tool_call_repo: Any | None = None,
) -> dict:
    """Build a deepagents SubAgent dict for the given subagent name."""
    description = SUBAGENT_CONFIGS[name]
    spec: dict = {
        "name": name,
        "description": description,
        "system_prompt": load_prompt(name),
        "tools": (
            await scope_agent_tools(mcp_client, name, store, review_session_id, tool_call_repo)
            + build_shared_memory_tools()
            + build_private_memory_tools(name)
        ),
    }
    if store is not None:
        spec["middleware"] = [SubagentCaptureMiddleware(name, store)]
    return spec
