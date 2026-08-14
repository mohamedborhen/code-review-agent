"""Per-subagent capture for the audit trail: real durations + tool-call events.

deepagents only surfaces the ROOT message list after ``ainvoke``; a subagent's
internal MCP calls (e.g. compliance -> ``jira_get_issue``) are nested inside the
subagent graph and are invisible to ``_emit_events``. This closes that
observability gap in three complementary ways:

- ``tool_scoping.scope_agent_tools`` wraps each scoped MCP tool so its call and
  result are emitted to the event bus tagged with the owning subagent (the tool
  wrapper lives in ``tool_scoping.py`` so the agent name is known by
  construction — no guessing who called what).
- ``SubagentCaptureMiddleware`` (this module) is attached to each subagent and
  records that subagent's total wall-clock time, so ``AgentExecution`` rows carry
  a real ``duration_ms`` instead of the hardcoded 0.
- The same middleware wraps the subagent's model call and emits every assistant
  message the model produces — reasoning text, *attempted* tool calls
  (``tool_call_attempt``) and rejected tool calls (``invalid_tool_call``). This
  exposes what the model did even when a call never reached a tool (e.g. a
  long-reasoning turn that ends with an empty assistant message, or a malformed
  tool call the runtime discards before execution). Executed calls appear as
  ``tool_call``/``tool_result`` from the tool wrapper; a ``tool_call_attempt``
  with no matching ``tool_call`` proves the runtime rejected it.
"""

import json
import logging
import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from deepagents._models import get_model_identifier, model_matches_spec

from infrastructure.agents_runtime.report_parse import report_dict_from_text
from infrastructure.config import settings
from infrastructure.event_bus.log_event_bus import _append_to_file, log_event

logger = logging.getLogger(__name__)

_CAPTURE_CONTENT_MAX_CHARS = 4000


def _truncate(text: str, limit: int = _CAPTURE_CONTENT_MAX_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def _model_label(model: object) -> str:
    """Best-effort model identifier for event/timeline labelling."""
    try:
        identifier = get_model_identifier(model)  # type: ignore[arg-type]
        if identifier:
            return str(identifier)
    except Exception:  # noqa: BLE001 - best-effort labelling must never break a review
        pass
    return str(getattr(model, "model_id", None) or "unknown")


def canonical_model_label(model: object) -> str:
    """Canonical model spec shared by every audit location.

    ``_model_label`` returns the provider-native identifier (e.g.
    ``nvidia/nemotron-...``), dropping the ``provider:`` prefix, so
    ``ReviewSession.model`` (the full ``settings.review_model`` spec) and
    ``AgentExecution.model`` (the captured label) disagreed. When the model
    instance matches ``settings.review_model`` (``model_matches_spec``
    normalizes provider spelling/case), return the canonical full spec
    verbatim; otherwise fall back to ``_model_label`` so future per-agent
    models still get a best-effort label.
    """
    try:
        if model_matches_spec(model, settings.review_model):  # type: ignore[arg-type]
            return settings.review_model
    except Exception:  # noqa: BLE001 - best-effort labelling must never break a review
        pass
    return _model_label(model)


class CaptureStore:
    """Per-request capture buffer shared by subagent middleware and the route."""

    def __init__(self) -> None:
        self._durations: dict[str, list[int]] = {}
        self._models: dict[str, str] = {}
        self._timeline: dict[str, list[dict]] = {}
        # Last report-shaped JSON dict emitted by each subagent, per invocation.
        # FIFO list so a re-dispatched agent (LLM-driven 2x delegation) pairs
        # each task ToolMessage with its own run's report in order.
        self._reports: dict[str, list[dict]] = {}

    def record_duration(self, agent_name: str, duration_ms: int) -> None:
        self._durations.setdefault(agent_name, []).append(duration_ms)

    def consume_duration(self, agent_name: str) -> int:
        pending = self._durations.get(agent_name)
        if not pending:
            return 0
        return pending.pop(0)

    def record_model(self, agent_name: str, model: str) -> None:
        self._models.setdefault(agent_name, model)

    def consume_model(self, agent_name: str) -> str | None:
        return self._models.get(agent_name)

    def record_call(self, agent_name: str, kind: str, name: str, duration_ms: int) -> None:
        self._timeline.setdefault(agent_name, []).append(
            {"kind": kind, "name": name, "duration_ms": duration_ms}
        )

    def consume_timeline(self) -> dict[str, list[dict]]:
        timeline = self._timeline
        self._timeline = {}
        return timeline

    def record_report(self, agent_name: str, report: dict) -> None:
        self._reports.setdefault(agent_name, []).append(report)

    def consume_report(self, agent_name: str) -> dict | None:
        pending = self._reports.get(agent_name)
        if not pending:
            return None
        return pending.pop(0)


class SubagentCaptureMiddleware(AgentMiddleware[Any, Any, Any]):
    """Times a subagent run and captures its model messages.

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

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        start = time.monotonic()
        response = handler(request)
        self._record_call(request, int((time.monotonic() - start) * 1000))
        self._stash_reports(response)
        for entry in self._build_entries(response):
            line = json.dumps(entry, default=str)
            logger.info("EVENT %s", line)
            _append_to_file(line)
        return response

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        start = time.monotonic()
        response = await handler(request)
        await self._arecord_call(request, int((time.monotonic() - start) * 1000))
        self._stash_reports(response)
        for entry in self._build_entries(response):
            await log_event(
                entry["type"],
                agent=self._agent_name,
                content=entry.get("content"),
                tool=entry.get("tool"),
                input_=entry.get("input"),
            )
        return response

    def _stash_reports(self, response: Any) -> None:
        """Stash the last report-shaped JSON each subagent emitted.

        A weak model sometimes produces its real SubagentReport JSON in an
        earlier message and then closes the run with prose or an empty message;
        the final ``task`` ToolMessage (what ``_extract_per_agent`` parses) is
        then not parseable and the findings would be lost. Every AIMessage the
        model emits passes through here (this middleware wraps the model call),
        so the last report-shaped dict is stashed per invocation for recovery.
        """
        if hasattr(response, "result"):
            messages = response.result
        elif isinstance(response, AIMessage):
            messages = [response]
        else:
            messages = []
        for msg in messages:
            if not isinstance(msg, AIMessage):
                continue
            report = report_dict_from_text(str(msg.content or ""))
            if report is not None:
                self._store.record_report(self._agent_name, report)

    def _record_call(self, request: Any, duration_ms: int) -> None:
        model = canonical_model_label(getattr(request, "model", None))
        self._store.record_call(self._agent_name, "llm", model, duration_ms)
        self._store.record_model(self._agent_name, model)
        line = json.dumps(
            {"type": "llm_call", "agent": self._agent_name, "content": model, "duration_ms": duration_ms},
            default=str,
        )
        logger.info("EVENT %s", line)
        _append_to_file(line)

    async def _arecord_call(self, request: Any, duration_ms: int) -> None:
        model = canonical_model_label(getattr(request, "model", None))
        self._store.record_call(self._agent_name, "llm", model, duration_ms)
        self._store.record_model(self._agent_name, model)
        await log_event("llm_call", agent=self._agent_name, content=model, duration_ms=duration_ms)

    def _build_entries(self, response: Any) -> list[dict]:
        """Turn one model response into event-log entries for this subagent."""
        if hasattr(response, "result"):
            messages = response.result
        elif isinstance(response, AIMessage):
            messages = [response]
        else:
            messages = []

        entries: list[dict] = []
        for msg in messages:
            if not isinstance(msg, AIMessage):
                continue

            text = str(msg.content or "")
            reasoning = ""
            for key in ("reasoning", "reasoning_content"):
                val = (msg.additional_kwargs or {}).get(key)
                if val:
                    reasoning += "\n" + str(val)
            combined = (text + reasoning).strip()
            if combined:
                entries.append(
                    {"type": "thinking", "content": _truncate(combined)}
                )

            for tc in msg.tool_calls or []:
                entries.append(
                    {
                        "type": "tool_call_attempt",
                        "tool": tc.get("name"),
                        "input": _truncate(json.dumps(tc.get("args", {}), default=str)),
                    }
                )
            for tc in msg.invalid_tool_calls or []:
                entries.append(
                    {
                        "type": "invalid_tool_call",
                        "tool": tc.get("name"),
                        "input": _truncate(json.dumps(tc.get("args", {}), default=str)),
                    }
                )
        return entries

    def _record(self) -> None:
        if self._t0 is not None:
            self._store.record_duration(self._agent_name, int((time.monotonic() - self._t0) * 1000))
            self._t0 = None
