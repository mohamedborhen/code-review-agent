"""Safety harness profile for the review agents.

create_deep_agent always injects a default tool suite (ls, read_file,
write_file, edit_file, delete, glob, grep, execute) into the root agent and
every subagent; the ``tools`` parameter is strictly additive and can never
remove them. The review agents must have exactly their assigned MCP tools and
NOTHING else — a write/execute-capable default suite is a direct violation of
the project's no-auto-apply safety rule.

The documented mechanism to drop built-ins is a HarnessProfile with
``excluded_tools`` (applied via _ToolExclusionMiddleware after all
tool-injecting middleware has run).

create_deep_agent looks the profile up two different ways depending on how
the model was constructed: by the raw model spec string (spec path), or — for
pre-built model instances — by the resolved provider:identifier (e.g.
``NVIDIA:z-ai/glm-5.2``). Registering only under ``settings.review_model``
therefore silently misses the pre-built path and drops the exclusion. We
resolve the model once at registration time and register under every lookup
shape, derived at runtime so no provider/model name is hardcoded.
"""

import logging

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)
from deepagents._models import get_model_identifier, get_model_provider
from langchain.chat_models import init_chat_model

from infrastructure.agents_runtime.middleware import NemotronNameParametersToolCallParser
from infrastructure.config import settings

logger = logging.getLogger(__name__)

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


def _harness_profile_keys() -> set[str]:
    """Return every key under which deepagents may look the profile up.

    The spec path keys on the raw model string; the pre-built path keys on the
    resolved model's ``provider:identifier`` (falling back to the bare
    provider). Deriving both from the live model keeps this provider-agnostic.
    """
    keys: set[str] = {settings.review_model}
    try:
        model = init_chat_model(settings.review_model)
    except Exception as exc:  # noqa: BLE001 - registration must never crash a review
        logger.warning("Could not resolve %s for harness profile keys: %s", settings.review_model, exc)
        return keys

    identifier = get_model_identifier(model)
    provider = get_model_provider(model)
    if provider and identifier and ":" not in identifier:
        keys.add(f"{provider}:{identifier}")
    elif identifier and ":" in identifier:
        keys.add(identifier)
    if provider:
        keys.add(provider)
    return keys


def ensure_review_harness_profile() -> None:
    """Register (merge) the review harness profile for the configured model."""
    profile = HarnessProfile(
        excluded_tools=_BUILTIN_TOOLS,
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        extra_middleware=[NemotronNameParametersToolCallParser()],
    )
    for key in _harness_profile_keys():
        register_harness_profile(key, profile)
