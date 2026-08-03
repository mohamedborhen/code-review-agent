"""Safety harness profile for the review agents.

create_deep_agent always injects a default tool suite (ls, read_file,
write_file, edit_file, delete, glob, grep, execute) into the root agent and
every subagent; the ``tools`` parameter is strictly additive and can never
remove them. The review agents must have exactly their assigned MCP tools and
NOTHING else — a write/execute-capable default suite is a direct violation of
the project's no-auto-apply safety rule.

The documented mechanism to drop built-ins is a HarnessProfile with
``excluded_tools`` (applied via _ToolExclusionMiddleware after all
tool-injecting middleware has run). It is registered under the configured
model spec string because create_deep_agent resolves the profile by exact
key on the model string passed to it.
"""

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile

from infrastructure.config import settings

# Built-in tools to strip from every stack. `task` is deliberately NOT in the
# set — the orchestrator needs it to delegate to subagents.
_BUILTIN_TOOLS: frozenset[str] = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
        "execute",
    }
)


def ensure_review_harness_profile() -> None:
    """Register (merge) the review harness profile for the configured model."""
    register_harness_profile(
        settings.review_model,
        HarnessProfile(
            excluded_tools=_BUILTIN_TOOLS,
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
