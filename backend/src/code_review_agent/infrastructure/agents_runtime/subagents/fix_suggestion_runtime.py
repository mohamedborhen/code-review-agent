"""Fix Suggestion subagent runtime: builds the deepagents SubAgent dict.

Has refactor_tool (preview) but NEVER apply_refactor_tool -- see AGENTS.md
Safety & Correctness Rules.
"""

from functools import partial

from infrastructure.agents_runtime.subagents.factory import build_subagent_spec

build_fix_suggestion_spec = partial(build_subagent_spec, "fix_suggestion")
