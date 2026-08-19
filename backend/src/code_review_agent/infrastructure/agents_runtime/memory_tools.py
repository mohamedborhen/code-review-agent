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

from langchain_core.tools import StructuredTool
from langmem import create_manage_memory_tool, create_search_memory_tool
from pydantic import BaseModel, Field

# Shared memory scope: every agent in a conversation, per user AND per repo.
SHARED_MEMORY_NAMESPACE: tuple[str, ...] = (
    "memories",
    "shared",
    "{user_id}",
    "{repo_id}",
)


# Explicit tool contract (P4 steering, 2026-08-19): langmem's shipped
# description never states that content is required for create, so weak models
# emit content-less create calls. The contract below replaces the passthrough
# description so the model sees the rule up front.
_MANAGE_MEMORY_DESCRIPTION: str = (
    "Create, update, or delete a long-term memory fact that persists across conversations.\n\n"
    "HARD CONTRACT:\n"
    "- create (default): store a NEW fact. content is REQUIRED - put the exact fact text there. "
    "NEVER call create without content: empty/missing content is REJECTED (error returned, nothing saved).\n"
    "- update: change an existing memory. Provide id (the id returned when it was created) AND the new content.\n"
    "- delete: remove an existing memory. Provide id only.\n"
    "- id: ONLY for update/delete. NEVER supply id when creating - the system assigns one."
)


class _ManageMemoryArgs(BaseModel):
    """Args for manage_memory, with the create-contract made explicit.

    Field names/types mirror langmem's own schema (so validation is unchanged)
    but every field carries a description that spells out the hard contract the
    model must follow (P4 steering).
    """

    action: str = Field(
        default="create",
        description=(
            "create (default): store a NEW fact; update: overwrite an existing "
            "memory; delete: remove one."
        ),
    )
    content: str | None = Field(
        default=None,
        description=(
            "The exact fact text to persist. MANDATORY for action=create - a create "
            "without content is REJECTED (error returned, nothing saved). Never omit "
            "content when creating."
        ),
    )
    id: str | None = Field(
        default=None,
        description=(
            "Memory id - ONLY for update/delete (the id the tool returned when the "
            "memory was created). NEVER provide id for action=create."
        ),
    )


def _harden_manage_memory_tool(tool: StructuredTool) -> StructuredTool:
    """Return a review-proof ``manage_memory`` (P2, E2E session 122).

    langmem's ``manage_memory`` raises a hard ``ValueError`` when a model passes
    an ``id`` with ``action=create`` (or omits ``id`` for update/delete). Left
    unhandled, that exception aborts the whole agent run and 500s the review.
    This wrapper:
    - normalizes ``create`` + stray ``id`` into a plain ``create`` so the write
      actually persists (langmem would otherwise reject it);
    - enforces non-empty ``content`` on ``create`` (P3) — a content-less create
      returns a structured error string instead of persisting ``{"content":null}``;
    - dedups exact-content ``create`` calls against the store (P3/3b) so repeated
      identical facts are idempotent instead of accumulating duplicate rows;
    - returns any remaining validation/store error as a STRING result, which
      deepagents feeds back to the model for self-correction.
    A memory-tool failure must never fail a review (PHASE_4.md §5.3 spirit).
    """

    async def _managed(**kwargs: object) -> str:
        action = kwargs.get("action", "create")
        if action == "create" and kwargs.get("id") is not None:
            kwargs = {**kwargs, "id": None}
        if action == "create":
            content = kwargs.get("content")
            if content is None or (isinstance(content, str) and not content.strip()):
                return (
                    "manage_memory error: content is required for action=create; "
                    "include a non-empty 'content' string (the fact to remember)."
                )
            existing = await _existing_memory_id(tool, content)
            if existing is not None:
                return f"already stored memory {existing}"
        try:
            result = await tool.ainvoke(kwargs)
        except Exception as exc:  # noqa: BLE001 - tool errors are model input
            return f"manage_memory error: {type(exc).__name__}: {exc}"
        return str(result)

    return StructuredTool.from_function(
        coroutine=_managed,
        name=tool.name,
        description=_MANAGE_MEMORY_DESCRIPTION,
        args_schema=_ManageMemoryArgs,
        handle_tool_error=tool.handle_tool_error,
    )


def _namespace_template_of(tool: StructuredTool):
    """Locate the LangMem NamespaceTemplate in a memory tool's closure.

    langmem binds the template as a closure cell; locating it by type (instead
    of a positional index) keeps this robust across tool kinds. The harden
    wrapper re-wraps the manage tool in a StructuredTool, so the template can
    sit one level deeper — a cell holding another tool is unwrapped and
    re-scanned (mirrors tests/test_memory_phase4.py::_namespace_template_of).
    """
    from langmem.utils import NamespaceTemplate

    stack = [tool]
    while stack:
        current = stack.pop()
        for cell in getattr(current.coroutine, "__closure__", ()) or ():
            if isinstance(cell.cell_contents, NamespaceTemplate):
                return cell.cell_contents
            if isinstance(cell.cell_contents, StructuredTool):
                stack.append(cell.cell_contents)
    return None


async def _existing_memory_id(tool: StructuredTool, content: str) -> str | None:
    """Return the id of an existing memory whose content matches exactly, else None.

    Cross-run idempotent create (P3/3b): the store's ``asearch`` is
    exact-namespace only (no index — the project's anti-vector decision,
    PHASE_4.md §6.4), so langmem's semantic dedup can never run; without this
    guard, repeated identical ``create`` calls persist duplicate rows (E2E S3
    stored the same fact three times). The store + identity come from the
    LangGraph runtime context (``get_store`` / ``get_config``), the same source
    langmem's tool uses, so no tool-argument or signature change is needed.
    Best-effort: any failure here falls through to a normal create.
    """
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        from langgraph.config import get_config, get_store

        config = get_config()
        store = get_store()
        template = _namespace_template_of(tool)
        if template is None:
            return None
        namespace = template(config)
        items = await store.asearch(namespace, limit=100)
        for item in items:
            if isinstance(item.value, dict) and item.value.get("content") == content:
                return str(item.key)
    except Exception:  # noqa: BLE001 - dedup is best-effort, never blocks a create
        return None
    return None


def build_shared_memory_tools() -> list:
    """Manage + search tools for the shared namespace (root + every subagent)."""
    return [
        _harden_manage_memory_tool(create_manage_memory_tool(SHARED_MEMORY_NAMESPACE)),
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
        _harden_manage_memory_tool(create_manage_memory_tool(namespace)),
        create_search_memory_tool(namespace),
    ]
