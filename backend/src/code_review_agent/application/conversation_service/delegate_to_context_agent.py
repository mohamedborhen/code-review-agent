"""Use-case service: decide when to recall historical context (PHASE_3.md §6).

The Context Agent is triggered by Layer 3 when historical context is missing
or explicitly referenced by the user. The actual search_messages network call
happens through the injected ContextAgentPort (implemented by infra) — this
module owns the *decision* and the audit wiring, not the wire call.
"""

from application.conversation_service.ports import ContextAgentPort

_REFERENCE_MARKERS = (
    "context",
    "history",
    "previous",
    "earlier",
    "recall",
    "before",
    "last time",
    "we discussed",
    "as i said",
    "remember",
)


def should_recall(user_message: str) -> bool:
    """True when the user message references prior conversation history."""
    lowered = user_message.lower()
    return any(marker in lowered for marker in _REFERENCE_MARKERS)


async def delegate_to_context_agent(
    *,
    conversation_id: int,
    user_id: str,
    repo_id: str,
    query: str,
    context_agent: ContextAgentPort,
    limit: int = 10,
):
    """Delegate a context recall to the read-only Context Agent.

    Returns the ContextAgentPort result verbatim; the caller owns auditing and
    persistence. Identity is forwarded explicitly — never derived from MCP
    headers (PHASE_3.md §5, §9.5).
    """
    return await context_agent.search_context(
        conversation_id=conversation_id,
        user_id=user_id,
        repo_id=repo_id,
        query=query,
        limit=limit,
    )
