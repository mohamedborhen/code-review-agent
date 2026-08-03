"""Per-subagent capture for the audit trail: real durations + tool-call events.

deepagents only surfaces the ROOT message list after ``ainvoke``; a subagent's
internal MCP calls (e.g. compliance -> ``jira_get_issue``) are nested inside the
subagent graph and are invisible to ``_emit_events``. This closes that
observability gap in two complementary ways:

- ``tool_scoping.scope_agent_tools`` wraps each scoped MCP tool so its call and
  result are emitted to the event bus tagged with the owning subagent (the tool
  wrapper lives in ``tool_scoping.py`` so the agent name is known by
  construction — no guessing who called what).
- ``SubagentCaptureMiddleware`` (this module) is attached to each subagent and
  records that subagent's total wall-clock time, so ``AgentExecution`` rows carry
  a real ``duration_ms`` instead of the hardcoded 0.
"""

import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AnyMessage
from langchain_core.tools import BaseTool

from infrastructure.event_bus.log_event_bus import log_event


class CaptureStore:
    """Per-request capture buffer shared by subagent middleware and the route."""

    def __init__(self) -> None:
        self._durations: dict[str, list[int]] = {}

    def record_duration(self, agent_name: str, duration_ms: int) -> None:
        self._durations.setdefault(agent_name, []).append(duration_ms)

    def consume_duration(self, agent_name: str) -> int:
        pending = self._durations.get(agent_name)
        if not pending:
            return 0
        return pending.pop(0)


class SubagentCaptureMiddleware(AgentMiddleware[Any, Any, Any]):
    """Times a subagent run and records it in the shared CaptureStore.

    One instance is created per subagent spec per request (in ``build_*_spec``),
    so the agent name is known at construction time. Both sync and async hook
    variants are implemented because the agent loop may call either.
    """

    def __init__(self, agent_name: str, store: CaptureStore) -> None:
        self._agent_name = agent_name
        self._store = store
        self._t0: float | None = None

    def before_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        self._t0 = time.monotonic()
        return None

    async def abefore_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        self._t0 = time.monotonic()
        return None

    def after_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        self._record()
        return None

    async def aafter_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        self._record()
        return None

    def _record(self) -> None:
        if self._t0 is not None:
            self._store.record_duration(self._agent_name, int((time.monotonic() - self._t0) * 1000))
            self._t0 = None
