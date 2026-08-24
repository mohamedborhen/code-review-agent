"""Fix Suggestion subagent runtime: builds the deepagents SubAgent dict.

Has refactor_tool (preview) but NEVER apply_refactor_tool — see AGENTS.md
Safety & Correctness Rules.
"""

from infrastructure.agents_runtime.subagents.factory import (  # noqa: F401
    build_subagent_spec as build_fix_suggestion_spec,
)
