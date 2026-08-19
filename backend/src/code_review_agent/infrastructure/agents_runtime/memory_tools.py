"""LangMem tool factories for shared + private long-term memory (Phase 4).

Pure tool construction — no business logic, no store wiring (the tools are
constructed WITHOUT ``store=`` so they resolve the graph's BaseStore at runtime
from ``create_deep_agent(store=...)``, PHASE_4.md §6.1).

Two scope kinds, both keyed by ``{user_id}`` + ``{repo_id}`` (never cross-repo
memory bleed):

- Shared: ``("memories", "shared", "{user_id}", "{repo_id}")`` — readable and
  writable by every agent in a conversation.
- Private: ``("memories", "private", "{user_id}", "{repo_id}", "<agent name>")``
  — readable and writable only by that subagent (the agent name is a LITERAL
  baked in at construction time, so another agent cannot address it).

The ``{placeholder}`` segments are a LangGraph runtime mechanism: they resolve
from ``config={"configurable": {"user_id": ..., "repo_id": ...}}`` at
``ainvoke`` time — never an LLM-fillable tool argument (PHASE_4.md §6.2).

These are native LangChain tools, NOT MCP tools: they are never added to
``AGENT_TOOL_PLAN`` and never routed through ``scope_agent_tools`` (PHASE_4.md
§2). ``manage_memory`` is the ONLY write-capable tool in the system; it is
bounded to the memory namespaces below — it grants no write access to any
existing table and no other write tool is added anywhere else (PHASE_4.md §2,
flagged write-tool exception).
"""

from langmem import create_manage_memory_tool, create_search_memory_tool

# Shared memory scope: every agent in a conversation, per user AND per repo.
SHARED_MEMORY_NAMESPACE: tuple[str, ...] = (
    "memories",
    "shared",
    "{user_id}",
    "{repo_id}",
)


def build_shared_memory_tools() -> list:
    """Manage + search tools for the shared namespace (root + every subagent)."""
    return [
        create_manage_memory_tool(SHARED_MEMORY_NAMESPACE),
        create_search_memory_tool(SHARED_MEMORY_NAMESPACE),
    ]


def build_private_memory_tools(agent_name: str) -> list:
    """Manage + search tools for one subagent's private namespace.

    ``agent_name`` is the literal subagent name (compliance, security,
    performance, regression, fix_suggestion) baked into the namespace, so no
    other agent can address this scope.
    """
    namespace: tuple[str, ...] = (
        "memories",
        "private",
        "{user_id}",
        "{repo_id}",
        agent_name,
    )
    return [
        create_manage_memory_tool(namespace),
        create_search_memory_tool(namespace),
    ]
