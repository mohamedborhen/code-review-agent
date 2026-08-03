"""Routing policy: maps a request_type to the list of review agents that run.

This is a plain Python module — no framework imports. The policy mirrors
PHASE_2.md's YAML exactly. `agents_for_request` returns:

- a non-empty list for request types that dispatch subagents
- `[]` for a *valid* request type with no subagents (orchestrator answers directly)
- `None` for an *unknown* request type (caller raises a 400)
"""

from typing import Final

ROUTING_POLICY: Final[dict[str, list[str]]] = {
    "review": ["compliance", "security", "performance", "regression"],
    "security_question": ["security"],
    "impact_question": ["regression"],
    "explain_question": [],
}


def agents_for_request(request_type: str) -> list[str] | None:
    """Return the agent list for a request_type, or None if unknown."""
    return ROUTING_POLICY.get(request_type)
