"""Model-call middleware for the deep agent loop: retry, timing, diff determinism.

These run on the model-call boundary (the root agent and, for
``TransientRetryMiddleware``, every subagent), so they can observe and repair
the exact messages the orchestrator produces before they reach the tool
executor:

- ``TransientRetryMiddleware`` retries a single model call on transient
  provider errors (429 / 5xx / rate limit / quota exhaustion / socket timeout /
  connection reset) with exponential backoff + jitter. Surgical — a
  rate-limited call never re-runs the whole multi-agent session.
- ``RootTimingMiddleware`` times every root model call (orchestrator classify,
  delegation reasoning, aggregator synthesis) and records the ordered timeline
  that becomes the per-agent latency report.
- ``DiffInjectionMiddleware`` guarantees the diff a specialist subagent sees is
  byte-for-byte identical to the request payload. The orchestrator never reads
  the diff (it was removed from the user message), so it cannot rewrite,
  summarize, abbreviate, or truncate it — the middleware appends the canonical
  diff to every ``task`` tool-call description programmatically.
"""

import asyncio
import json
import logging
import random
import re
import time
import uuid

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ExtendedModelResponse, ModelResponse
from langchain_core.messages import AIMessage

from infrastructure.agents_runtime.capture import CaptureStore, canonical_model_label
from infrastructure.event_bus.log_event_bus import _append_to_file, log_event

logger = logging.getLogger(__name__)

# Sentinel markers framing the injected diff block. They make locating and
# replacing the block unambiguous even if the model's prose mentions "Diff:".
DIFF_BEGIN = "<<<REVIEW_DIFF>>>"
DIFF_END = "<<<END_REVIEW_DIFF>>>"

_TRANSIENT_PROVIDER_PATTERN = re.compile(
    r"(?i)(429|5\d\d|too many requests|rate ?limit|resource ?exhausted|"
    r"insufficient_quota|overloaded|timeout on reading data from socket|"
    r"timed ?out|read timed out|connection reset|apiconnectionerror|"
    r"connectionerror|econnreset|etimedout|bad gateway|service unavailable|"
    r"gateway timeout)"
)


def _is_transient_provider_error(exc: Exception) -> bool:
    """True for provider errors that can succeed on retry.

    Matches the provider-side conditions observed in live sessions (OpenRouter
    504/429, NVIDIA 503 ResourceExhausted, socket timeouts). Deliberately does
    NOT match 400/401/403/404 — those are config/auth/not-found conditions where
    retrying would just burn quota.
    """
    return bool(_TRANSIENT_PROVIDER_PATTERN.search(str(exc)))


class TransientRetryMiddleware(AgentMiddleware):
    """Retry an individual model call on transient provider errors.

    Attached to the root and every subagent stack. deepagents resolves provider
    profiles once per call, so retrying ``handler(request)`` re-invokes the
    provider with the same request — safe for rate-limited/quota/timeout
    conditions.
    """

    def __init__(self, attempts: int = 3, base_delay: float = 2.0, max_delay: float = 30.0) -> None:
        self._attempts = attempts
        self._base_delay = base_delay
        self._max_delay = max_delay

    def _delay(self, attempt: int) -> float:
        delay = self._base_delay * (2 ** attempt)
        if delay > 0:
            delay += random.uniform(0, 1)
        return min(delay, self._max_delay)

    def wrap_model_call(self, request, handler):
        for attempt in range(self._attempts):
            try:
                return handler(request)
            except Exception as exc:  # noqa: BLE001 - retry classification
                if not _is_transient_provider_error(exc) or attempt == self._attempts - 1:
                    raise
                time.sleep(self._delay(attempt))
        raise RuntimeError("unreachable")  # pragma: no cover

    async def awrap_model_call(self, request, handler):
        for attempt in range(self._attempts):
            try:
                return await handler(request)
            except Exception as exc:  # noqa: BLE001 - retry classification
                if not _is_transient_provider_error(exc) or attempt == self._attempts - 1:
                    raise
                delay = self._delay(attempt)
                logger.warning(
                    "Transient provider error (attempt %s/%s), retrying in %.1fs: %s",
                    attempt + 1,
                    self._attempts,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")  # pragma: no cover


class RootTimingMiddleware(AgentMiddleware):
    """Time each root model call (orchestrator/aggregator) into the CaptureStore."""

    def __init__(self, store: CaptureStore) -> None:
        self._store = store

    def _record(self, model: str, duration_ms: int) -> None:
        self._store.record_call("orchestrator", "llm", model, duration_ms)
        self._store.record_model("orchestrator", model)

    def wrap_model_call(self, request, handler):
        start = time.monotonic()
        response = handler(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        self._record(canonical_model_label(request.model), duration_ms)
        line = json.dumps(
            {"type": "llm_call", "agent": "orchestrator", "content": canonical_model_label(request.model), "duration_ms": duration_ms},
            default=str,
        )
        logger.info("EVENT %s", line)
        _append_to_file(line)
        return response

    async def awrap_model_call(self, request, handler):
        start = time.monotonic()
        response = await handler(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        model = canonical_model_label(request.model)
        self._record(model, duration_ms)
        await log_event("llm_call", agent="orchestrator", content=model, duration_ms=duration_ms)
        return response


class DiffInjectionMiddleware(AgentMiddleware):
    """Append the canonical diff to every ``task`` tool-call description.

    The orchestrator's user message no longer contains the diff (see
    ``orchestrator_runtime._build_user_message``), so the model cannot
    paraphrase it. After each root model response, every ``task`` tool-call's
    ``description`` argument is rebuilt so it ends with the exact request diff,
    framed by sentinel markers for unambiguous location/replacement. If the
    model still attempted to attach its own diff text, that block is discarded
    first. Idempotent: an already-exact diff is left untouched.
    """

    def __init__(self, diff_content: str | None) -> None:
        diff = diff_content or ""
        # Keep the diff byte-for-byte (including any trailing newline) — only
        # strip to decide whether it is effectively empty.
        self._diff = diff if diff.strip() else ""

    def _repair_description(self, description: str) -> tuple[str, bool]:
        if not self._diff:
            return description, False
        base = description or ""
        for marker in (DIFF_BEGIN, "Diff:"):
            idx = base.find(marker)
            if idx != -1:
                base = base[:idx].rstrip()
                break
        block = f"\n\n{DIFF_BEGIN}\n{self._diff}\n{DIFF_END}"
        repaired = base + block
        return repaired, repaired != description

    def _repair_response(self, response: ModelResponse) -> tuple[ModelResponse, bool]:
        if not self._diff:
            return response, False
        result = list(response.result)
        replaced = False
        for i, msg in enumerate(result):
            if not isinstance(msg, AIMessage) or not msg.tool_calls:
                continue
            new_calls = list(msg.tool_calls)
            touched = False
            for j, tc in enumerate(new_calls):
                if tc.get("name") != "task":
                    continue
                args = dict(tc.get("args") or {})
                description, changed = self._repair_description(args.get("description", ""))
                if changed:
                    args["description"] = description
                    new_calls[j] = {**tc, "args": args}
                    touched = True
            if touched:
                result[i] = msg.model_copy(update={"tool_calls": new_calls})
                replaced = True
        if replaced:
            response = ModelResponse(result=result, structured_response=response.structured_response)
        return response, replaced

    def wrap_model_call(self, request, handler):
        response, replaced = self._repair_response(handler(request))
        if replaced:
            line = json.dumps({"type": "diff_injected", "agent": "orchestrator"}, default=str)
            logger.info("EVENT %s", line)
            _append_to_file(line)
        return response

    async def awrap_model_call(self, request, handler):
        response, replaced = self._repair_response(await handler(request))
        if replaced:
            await log_event("diff_injected", agent="orchestrator", content="repaired task description(s) with canonical diff")
        return response


def _request_tool_names(request: object) -> list[str]:
    """Extract tool names from a model-call request (tools list).

    `ModelRequest.tools` holds `BaseTool | dict` entries; the OpenAI-function
    dict form names the tool under ``function.name``.
    """
    names: list[str] = []
    for tool in getattr(request, "tools", None) or []:
        if isinstance(tool, dict):
            name = tool.get("name")
            if isinstance(name, str):
                names.append(name)
                continue
            function = tool.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                names.append(function["name"])
                continue
        name = getattr(tool, "name", None)
        if isinstance(name, str):
            names.append(name)
    return names


def _calls_from_name_parameters(candidates: list[dict], valid_tools: set[str] | None) -> list[dict]:
    """Convert `{"name":..., "parameters":...}` dicts into LangChain tool calls.

    Filters against ``valid_tools`` (when provided) so a text-form call is
    never synthesized for a tool the stack does not actually expose.
    """
    calls: list[dict] = []
    for obj in candidates:
        name = obj.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if valid_tools is not None and name not in valid_tools:
            continue
        params = obj.get("parameters")
        if not isinstance(params, dict):
            params = obj.get("args")
        if not isinstance(params, dict):
            params = {}
        calls.append({"name": name, "args": params, "id": uuid.uuid4().hex, "type": "tool_call"})
    return calls


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Drop the byte spans (JSON objects/arrays) from `text`, preserving prose."""
    if not spans:
        return text
    spans = sorted(spans)
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts).strip()


def _extract_name_parameters_calls(
    content: str, valid_tools: set[str] | None
) -> tuple[list[dict], str]:
    """Parse Nemotron text-form tool calls: `[{"name":..., "parameters":{...}}]`.

    Handles the exact format observed from ``nemotron-3-ultra-550b-a55b``
    (E2E sessions 119-121, 126): the model emits tool intent as a JSON array
    in message content instead of native structured ``tool_calls``. Tolerates
    the nested double-array shape (``[[{...}]]``), multiple tool objects in
    one array, and prose wrapped around the JSON. Returns ``(calls, leftover)``
    where ``leftover`` is the content minus the parsed JSON.
    """
    text = content.strip()
    if not text:
        return [], content

    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    spans: list[tuple[int, int]] = []

    def collect(item: object) -> None:
        if isinstance(item, dict):
            candidates.append(item)
        elif isinstance(item, list):
            for element in item:
                collect(element)

    # Whole-value array form first (covers `[...]` and nested `[[...]]`).
    start = text.find("[")
    if start != -1:
        try:
            arr, end = decoder.raw_decode(text[start:])
            collect(arr)
            if candidates:
                spans.append((start, start + end))
        except (json.JSONDecodeError, ValueError):
            pass

    # No array matched — scan for individual objects via raw_decode.
    if not candidates:
        idx = 0
        while True:
            obj_start = text.find("{", idx)
            if obj_start == -1:
                break
            try:
                obj, end = decoder.raw_decode(text[obj_start:])
            except (json.JSONDecodeError, ValueError):
                idx = obj_start + 1
                continue
            if isinstance(obj, dict):
                candidates.append(obj)
                spans.append((obj_start, obj_start + end))
            idx = obj_start + end

    calls = _calls_from_name_parameters(candidates, valid_tools)
    if not calls:
        return [], content
    return calls, _remove_spans(text, spans)


class NemotronNameParametersToolCallParser(AgentMiddleware):
    """Repair Nemotron text-form tool calls emitted as `name`/`parameters` JSON.

    Deepagents' built-in ``NemotronTextToolCallParser`` only recognizes
    ``<function=...>`` XML blocks and ``{"tool": ..., "args": ...}`` JSON.
    ``nemotron-3-ultra-550b-a55b`` instead emits tool calls as
    ``[{"name": ..., "parameters": {...}}, ...]`` text JSON arrays (root,
    subagent, and aggregator stacks alike), which the built-in parser misses
    entirely — so the call is never dispatched and the model loops to
    synthesis, fabricating a success report (E2E P1).

    This middleware runs after the built-in parser (harness-profile merge
    appends it last) and converts the `name`/`parameters` form into real
    ``tool_calls`` so deepagents dispatches them. Names are filtered against
    the tools the stack actually exposes — never a fabricated call.
    """

    name = "NemotronNameParametersToolCallParser"

    @staticmethod
    def _repair_message(message: AIMessage, valid_tools: set[str] | None = None) -> AIMessage:
        if message.tool_calls:
            return message
        content = message.content
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        else:
            text = ""
        calls, leftover = _extract_name_parameters_calls(text, valid_tools)
        if not calls:
            return message
        return message.model_copy(update={"tool_calls": calls, "content": leftover})

    @staticmethod
    def _repair_response(response: ModelResponse, valid_tools: set[str] | None = None) -> ModelResponse:
        result = list(response.result)
        changed = False
        for i, msg in enumerate(result):
            if isinstance(msg, AIMessage):
                fixed = NemotronNameParametersToolCallParser._repair_message(msg, valid_tools)
                if fixed is not msg:
                    result[i] = fixed
                    changed = True
        if not changed:
            return response
        return ModelResponse(result=result, structured_response=response.structured_response)

    @staticmethod
    def _repair(result: object, valid_tools: set[str] | None = None) -> object:
        if isinstance(result, ExtendedModelResponse):
            return ExtendedModelResponse(
                model_response=NemotronNameParametersToolCallParser._repair_response(
                    result.model_response, valid_tools
                ),
                command=result.command,
            )
        if isinstance(result, AIMessage):
            return NemotronNameParametersToolCallParser._repair_message(result, valid_tools)
        if isinstance(result, ModelResponse):
            return NemotronNameParametersToolCallParser._repair_response(result, valid_tools)
        return result

    def wrap_model_call(self, request, handler):
        return self._repair(handler(request), set(_request_tool_names(request)))

    async def awrap_model_call(self, request, handler):
        return self._repair(await handler(request), set(_request_tool_names(request)))


def render_timeline(timeline: dict[str, list[dict]]) -> str:
    """Render the per-agent call timeline in the requested latency-report shape.

    LLM calls are numbered per agent; the orchestrator's final LLM call (the
    aggregator synthesis) is labelled ``final synthesis``.
    """
    lines: list[str] = []
    for agent, calls in timeline.items():
        if not calls:
            continue
        lines.append(f"{agent}:")
        llm_counter = 0
        total = len(calls)
        for idx, call in enumerate(calls):
            kind = call.get("kind")
            name = call.get("name") or ""
            duration_ms = call.get("duration_ms", 0)
            secs = f"{duration_ms / 1000.0:.1f}s"
            if kind == "llm":
                llm_counter += 1
                label = "final synthesis" if agent == "orchestrator" and idx == total - 1 else f"LLM call #{llm_counter}"
                lines.append(f"  {label} ({name}): {secs}")
            else:
                lines.append(f"  {name}: {secs}")
    return "\n".join(lines)
