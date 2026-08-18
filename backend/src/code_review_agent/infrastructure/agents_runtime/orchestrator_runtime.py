"""Orchestrator + Aggregator runtime: Layer 5 implementation of ReviewOrchestratorPort.

Design notes:
- All five specialist subagents are registered on the deep agent (the DoD
  requires all 7 agents constructed via create_deep_agent, and the aggregator
  is the root agent's synthesis phase). The per-request REQUIRED set comes from
  the routing policy and is spelled out in the user message; the orchestrator
  must delegate to each required agent, and may additionally invoke
  fix_suggestion once findings exist.
- ``response_format=SubagentReport`` is set on the root; deepagents propagates
  it to every subagent, so each subagent's ToolMessage content is a
  JSON-serialized SubagentReport — that is what per-agent audit rows are parsed
  from.
- The safety harness profile strips every built-in filesystem/execute tool; the
  agents hold exactly their scoped MCP tools (plus the root's `task` tool).
"""

import asyncio
import json
import logging
import re

from deepagents import (
    ProviderProfile,
    create_deep_agent,
    register_provider_profile,
)
from langchain_core.messages import AIMessage, ToolMessage

from domain.entities.agent_finding import AgentFinding, AgentInput, AgentOutput, ReviewResult
from infrastructure.agents_runtime.capture import CaptureStore
from infrastructure.agents_runtime.harness_profile import ensure_review_harness_profile
from infrastructure.agents_runtime.middleware import (
    DiffInjectionMiddleware,
    RootTimingMiddleware,
    TransientRetryMiddleware,
    _is_transient_provider_error,
)
from infrastructure.agents_runtime.report_parse import extract_json_text as _extract_json
from infrastructure.agents_runtime.report_schema import FindingItem, SubagentReport
from infrastructure.agents_runtime.subagents.compliance_runtime import build_compliance_spec
from infrastructure.agents_runtime.subagents.context_agent_runtime import get_audited_context_tool
from infrastructure.agents_runtime.subagents.fix_suggestion_runtime import build_fix_suggestion_spec
from infrastructure.agents_runtime.subagents.performance_runtime import build_performance_spec
from infrastructure.agents_runtime.subagents.regression_runtime import build_regression_spec
from infrastructure.agents_runtime.subagents.security_runtime import build_security_spec
from infrastructure.agents_runtime.tool_scoping import load_prompt
from infrastructure.config import settings
from infrastructure.db.conversation_ports_adapters import SQLModelConversationAudit
from infrastructure.event_bus.log_event_bus import log_event

logger = logging.getLogger(__name__)

_SUBAGENT_BUILDERS = {
    "compliance": build_compliance_spec,
    "security": build_security_spec,
    "performance": build_performance_spec,
    "regression": build_regression_spec,
    "fix_suggestion": build_fix_suggestion_spec,
}

_ALL_SUBAGENTS = list(_SUBAGENT_BUILDERS)

# Typed request types that carry an optional user question: the single-
# specialist questions (compliance/security/performance/impact) forward the
# `question` field so the user can steer the specialist (e.g. a ticket key to
# check). `review` (full pipeline) forwards it too so users can give the
# orchestrator both the diff and a linked Jira ticket key in one prompt.
# `explain_question` (direct answer) stays without one.
_QUESTION_CARRYING_TYPES = frozenset(
    {"review", "compliance_question", "security_question", "performance_question", "impact_question"}
)


def _ensure_review_provider_profile() -> None:
    """Cap output tokens via a deepagents ProviderProfile.

    Registered under the exact `settings.review_model` key so deepagents'
    resolve_model forwards `max_tokens` to init_chat_model while the model
    stays a STRING — preserving the exact-key HarnessProfile lookup (see
    harness_profile.py). Keeps the OpenRouter free tier from rejecting the
    model's full 16k output window as unaffordable.
    """
    register_provider_profile(
        settings.review_model,
        ProviderProfile(
            init_kwargs={
                "max_tokens": settings.review_max_tokens,
                "timeout": settings.review_timeout,
            }
        ),
    )


class OrchestratorRuntime:
    """Builds and runs the deep agent (orchestrator + aggregator in one)."""

    def __init__(self, mcp_client, review_session_id: int | None = None) -> None:
        self._mcp_client = mcp_client
        self._review_session_id = review_session_id
        self.capture = CaptureStore()

    async def run_review(self, review_input: AgentInput, agent_names: list[str]) -> ReviewResult:
        ensure_review_harness_profile()
        _ensure_review_provider_profile()

        subagent_specs = []
        if agent_names:
            for name in _ALL_SUBAGENTS:
                spec = await _SUBAGENT_BUILDERS[name](self._mcp_client, self.capture)
                middleware = list(spec.get("middleware") or [])
                middleware.append(TransientRetryMiddleware())
                spec["middleware"] = middleware
                subagent_specs.append(spec)

        system_prompt = load_prompt("orchestrator") + "\n\n" + load_prompt("aggregator")
        user_message = _build_user_message(review_input, agent_names)

        root_middleware = [
            RootTimingMiddleware(self.capture),
            DiffInjectionMiddleware(review_input.diff_content),
            TransientRetryMiddleware(),
        ]

        # Root-agent tools: when historical conversation context is AVAILABLE
        # (conversation_id supplied), grant the Context Agent's single read-only
        # search_messages tool so the orchestrator can recall evidence BEFORE
        # delegating. Recall is optional — the orchestrator decides — so the
        # tool is only made reachable, never invoked on our behalf. When no
        # conversation is supplied, the root gets NO tools (Phase 2 behavior).
        # deepagents merges the `tools` argument additively with the built-in
        # suite, so `task` is preserved; the harness profile still strips the
        # filesystem/execute built-ins.
        root_tools = await _build_root_tools(
            review_input, self._mcp_client, self._review_session_id, self.capture
        )

        agent = create_deep_agent(
            model=settings.review_model,
            system_prompt=system_prompt,
            subagents=subagent_specs or None,
            response_format=SubagentReport,
            middleware=root_middleware,
            tools=root_tools,
        )

        result = await _run_with_retry(agent, user_message)
        messages = result.get("messages", [])

        await _emit_events(messages)

        return ReviewResult(
            aggregated=_parse_aggregated(result),
            per_agent=_extract_per_agent(messages, self.capture),
        )


async def _build_root_tools(
    review_input: AgentInput, mcp_client, review_session_id: int | None, store: CaptureStore
) -> list | None:
    """Return the root agent's tools, or None for the no-conversation path.

    A conversation_id only makes the Context Agent's search_messages tool
    reachable; it never forces a recall (the orchestrator decides). When no
    conversation is supplied, the root gets no tools and Phase 2 behavior is
    preserved byte-for-byte. Returns None (not []) when the tool is
    unavailable so callers can distinguish "no tools" from "tools withheld".

    Identity (conversation_id/user_id/repo_id) is bound into the tool at
    construction time (PHASE_3.md §9.5) — the LLM supplies only the query.
    """
    if review_input.conversation_id is None:
        return None
    if review_input.user_id is None:
        return None  # defensive: the route 400s earlier (_validate_conversation_identity)
    audited_context_tool = await get_audited_context_tool(
        mcp_client,
        conversation_id=review_input.conversation_id,
        user_id=review_input.user_id,
        repo_id=review_input.repo_id,
        audit=SQLModelConversationAudit(),
        review_session_id=review_session_id,
        store=store,
    )
    if audited_context_tool is None:
        return None
    return [audited_context_tool]


def _build_user_message(review_input: AgentInput, agent_names: list[str]) -> str:
    if review_input.request_type == "any_question":
        pool = ", ".join(agent_names) if agent_names else "(none)"
        lines = [
            f"Request type: {review_input.request_type}",
            f"Repo: {review_input.repo_id}",
            f"Graph commit hash: {review_input.graph_commit_hash}",
            f"Repo root (local path): {review_input.repo_root}",
            "",
            "Subagents need BOTH the repo identifier (owner/name from `Repo:`) for "
            "their GitHub tools AND the repo-root path (from `Repo root (local path):`) "
            "for their CRG tools. Include both in every task description, never omit one.",
            "",
            "Question from the user:",
            review_input.question or "(no question provided)",
            "",
            "Available subagents (delegate to the one(s) relevant to this question — "
            "one, several, or none if it is answerable directly):",
            pool,
            "",
            "Investigate, then synthesize the answer into a single SubagentReport JSON.",
        ]
        text = "\n".join(lines)
    else:
        required = ", ".join(agent_names) if agent_names else "(none — answer directly)"
        lines = [
            f"Request type: {review_input.request_type}",
            f"Repo: {review_input.repo_id}",
            f"Graph commit hash: {review_input.graph_commit_hash}",
            f"Repo root (local path): {review_input.repo_root}",
            "",
            "Subagents need BOTH the repo identifier (owner/name from `Repo:`) for "
            "their GitHub tools AND the repo-root path (from `Repo root (local path):`) "
            "for their CRG tools. Include both in every task description, never omit one.",
            "",
            "Required subagents for this request type (you MUST delegate to each):",
            required,
        ]
        if review_input.request_type in _QUESTION_CARRYING_TYPES and review_input.question:
            lines.extend(
                [
                    "",
                    "Question from the user:",
                    review_input.question,
                ]
            )
        diff_instructions = (
            "The complete, unmodified diff for this review is appended automatically to every "
            "task description by the system — you must not reproduce, summarize, abbreviate, "
            "or reference the diff text yourself."
            if review_input.diff_content
            else "There is no separate diff parameter for this review: any diff content the user "
            "supplied lives inside the 'Question from the user:' section above. Forward that "
            "question verbatim into every task description so subagents see the exact diff."
        )
        lines.extend(
            [
                "",
                diff_instructions,
                "",
                "Classify the request, delegate to every required subagent, then synthesize all "
                "reports into a single SubagentReport JSON.",
            ]
        )
        text = "\n".join(lines)

    if review_input.conversation_id is not None:
        text += "\n\n" + _conversation_context_block(review_input)
    return text


def _conversation_context_block(review_input: AgentInput) -> str:
    """Prompt block declaring historical context AVAILABLE (never mandatory).

    The orchestrator owns the recall decision (PHASE_3.md §6): conversation_id
    only makes search_messages reachable. Identity is closure-bound into the
    tool at construction time (§9.5), so the LLM no longer supplies — or sees —
    conversation_id/user_id/repo_id; it only provides the search query. When
    recall is warranted it must run BEFORE specialist delegation; results are
    evidence with message_id provenance — never a ready-made answer — and the
    most recent message wins on contradiction (§9.7).
    """
    return (
        "Historical conversation context is AVAILABLE (optional, not mandatory). "
        "The search_messages tool is pre-scoped to this conversation's identity — "
        "do not pass conversation_id/user_id/repo_id; they are supplied for you. "
        "You may call it ONLY if historical context is needed to answer this review; "
        "it is never required and must never be called on every request. If you call "
        "it, do so BEFORE delegating to subagents, treat the results as evidence "
        "(never answer from a single snippet — reason over all of them), retain the "
        "message_id of every hit you rely on, and when two recalled messages "
        "contradict, prefer the most recent one."
    )


def _index_task_calls(messages) -> dict[str, str]:
    """Map tool_call_id -> subagent_type for the root's `task` tool calls."""
    calls: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        for tc in msg.tool_calls or []:
            if tc.get("name") == "task":
                subagent_type = (tc.get("args") or {}).get("subagent_type")
                if subagent_type:
                    calls[tc.get("id")] = subagent_type
    return calls


def _to_agent_output(report: SubagentReport) -> AgentOutput:
    findings = [
        AgentFinding(
            severity=item.severity,
            confidence=item.confidence,
            title=item.title,
            description=item.description,
            evidence=list(item.evidence),
            recommendation=item.recommendation,
        )
        for item in report.findings
    ]
    return AgentOutput(agent_name=report.agent_name, findings=findings)


def _parse_aggregated(result: dict) -> AgentOutput:
    structured = result.get("structured_response")
    if isinstance(structured, SubagentReport):
        return AgentOutput(agent_name="aggregator", findings=_to_agent_output(structured).findings)
    from_dict: AgentOutput | None = None
    if isinstance(structured, dict):
        try:
            report = SubagentReport.model_validate(structured)
            return AgentOutput(agent_name="aggregator", findings=_to_agent_output(report).findings)
        except Exception:
            pass
        try:
            report = _coerce_report(json.dumps(structured), "aggregator")
            report.agent_name = "aggregator"
            from_dict = AgentOutput(agent_name="aggregator", findings=_to_agent_output(report).findings)
        except Exception:
            logger.warning("Aggregator structured response did not match SubagentReport schema")
    # Weak-model fallback: deepagents occasionally returns the aggregator report
    # as plain final-message content instead of a native structured response
    # (session 50 — full findings in the `final` event but findings:[] in the
    # API). Parse the last AIMessage content through the same lenient path used
    # for subagent tool messages, and prefer it whenever it carries findings —
    # otherwise an empty dict structured response (`{}`) would short-circuit
    # with zero findings and throw the real report away.
    from_messages = _parse_aggregated_from_messages(result)
    if from_messages is not None and from_messages.findings:
        return from_messages
    if from_dict is not None:
        return from_dict
    if from_messages is not None:
        return from_messages
    logger.warning("No structured_response in orchestrator result; returning empty aggregated output")
    return AgentOutput(agent_name="aggregator")


def _parse_aggregated_from_messages(result: dict) -> AgentOutput | None:
    """Parse the aggregator report from the last AIMessage content, if any.

    Mirror of `_parse_tool_message`: strip fences/XML, coerce leniently, and
    return None only when no message parses (caller then falls back to empty).
    """
    for msg in reversed(result.get("messages", [])):
        if not isinstance(msg, AIMessage) or not msg.content:
            continue
        try:
            report = _coerce_report(_extract_json(str(msg.content)), "aggregator")
            report.agent_name = "aggregator"
            return AgentOutput(agent_name="aggregator", findings=_to_agent_output(report).findings)
        except Exception:
            continue
    return None


def _parse_tool_message(agent_name: str, content) -> AgentOutput:
    if not content:
        return AgentOutput(agent_name=agent_name)
    text = content.content if hasattr(content, "content") else str(content)
    text = _extract_json(text)
    try:
        raw = json.loads(text)
    except Exception:
        raw = None
    if isinstance(raw, dict) and "findings" not in raw and raw.get("violations"):
        # compliance-style report: pydantic's default ignores unknown top-level
        # keys, so strict validation would "succeed" with empty findings and
        # silently drop the violations — route straight to the tolerant path.
        return _to_agent_output(_coerce_report(text, agent_name))
    try:
        report = SubagentReport.model_validate_json(text)
        return _to_agent_output(report)
    except Exception:
        pass
    try:
        report = _coerce_report(text, agent_name)
        return _to_agent_output(report)
    except Exception:
        logger.warning("Could not parse structured subagent output for %s", agent_name)
        return AgentOutput(agent_name=agent_name)


_STRING_CONFIDENCE: dict[str, float] = {
    "low": 0.3,
    "medium": 0.6,
    "high": 0.9,
    "critical": 1.0,
}

_STRUCTURED_OUTPUT_FAILURE = re.compile(r"structured output|json|parse", re.IGNORECASE)


async def _run_with_retry(agent, user_message: str, attempts: int = 3) -> dict:
    """Run the deep agent, retrying transient + structured-output failures.

    Two failure classes are retried, each with a cadence matching its nature:

    - Provider-transient errors (429 / 5xx / rate limit / quota / socket
      timeout) — exponential backoff. These are mostly absorbed earlier by
      ``TransientRetryMiddleware`` at the individual model-call level; this
      whole-run retry is the outer safety net.
    - Structured-output parse failures (a weak-model failure mode observed
      during E2E, where the configured model returns an empty/invalid native
      structured output that deepagents surfaces as a parse error) — short
      delay, since they are not quota-bound.

    Everything else propagates immediately.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await agent.ainvoke({"messages": [{"role": "user", "content": user_message}]})
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch for retry classification
            last = exc
            transient = _is_transient_provider_error(exc)
            structured = bool(_STRUCTURED_OUTPUT_FAILURE.search(str(exc)))
            if not (transient or structured):
                raise
            if attempt < attempts:
                delay = (2.0 * (2 ** (attempt - 1)) + 0.5) if transient else 0.5
                logger.warning(
                    "Retrying review run (attempt %s/%s) after %s: %s",
                    attempt,
                    attempts,
                    "transient provider error" if transient else "structured-output failure",
                    exc,
                )
                await asyncio.sleep(delay)
    raise last  # type: ignore[misc]


def _coerce_finding(item: dict) -> FindingItem:
    """Leniently coerce a raw finding dict into the strict FindingItem schema.

    Subagents regularly deviate from the exact schema — string confidences
    (``"high"``), evidence as dicts instead of list[str], a ``violations`` key
    instead of ``findings``. Without coercion those findings silently vanish
    from the AgentExecution audit rows. This is the single source of truth for
    the tolerant path; strict pydantic parsing is always attempted first.
    """
    confidence = item.get("confidence", 0.5)
    if isinstance(confidence, str):
        key = confidence.strip().lower()
        confidence = _STRING_CONFIDENCE.get(key, 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))

    evidence_raw = item.get("evidence")
    if not evidence_raw:
        evidence_raw = item.get("location")
    evidence: list[str] = []
    if isinstance(evidence_raw, str):
        evidence = [evidence_raw]
    else:
        for e in evidence_raw or []:
            if isinstance(e, str):
                evidence.append(e)
            else:
                evidence.append(json.dumps(e, ensure_ascii=False, default=str))

    if confidence == 0.5 and item.get("risk_score") is not None:
        try:
            confidence = min(1.0, max(0.0, float(item["risk_score"]) / 10.0))
        except (TypeError, ValueError):
            pass

    recommendation = item.get("recommendation")
    if not recommendation:
        recommendations = item.get("recommendations")
        if isinstance(recommendations, list):
            recommendation = "\n".join(str(r) for r in recommendations)
        elif recommendations:
            recommendation = str(recommendations)

    return FindingItem(
        severity=str(item.get("severity", "info")).lower(),
        confidence=confidence,
        title=str(item.get("title") or item.get("id") or ""),
        description=str(item.get("description", "")),
        evidence=evidence,
        recommendation=str(recommendation or ""),
    )


def _findings_list(raw: dict) -> list | None:
    """Locate the findings array under any of the shapes subagents emit.

    Subagents nest reports under domain keys (``security_review``,
    ``compliance_report``, ...) and vary the array name (``findings``,
    ``violations``, ``security_findings``, ...). Recurse one level into nested
    dicts so a report like ``{"security_review": {"findings": [...]}}`` parses.
    """
    for key in ("findings", "violations"):
        value = raw.get(key)
        if isinstance(value, list):
            return value
    for key, value in raw.items():
        if key.endswith("findings") and isinstance(value, list):
            return value
    for value in raw.values():
        if isinstance(value, dict):
            nested = _findings_list(value)
            if nested is not None:
                return nested
    return None


def _coerce_report(text: str, agent_name: str) -> SubagentReport:
    raw = json.loads(text)
    if not isinstance(raw, dict):
        return SubagentReport(agent_name=agent_name)
    findings_raw = _findings_list(raw) or []
    findings = [
        _coerce_finding(item)
        for item in findings_raw
        if isinstance(item, dict)
    ]
    return SubagentReport(
        agent_name=str(raw.get("agent_name") or agent_name),
        findings=findings,
    )


def _looks_like_json_obj(content) -> bool:
    """True when the final ToolMessage content is at least a JSON object.

    A valid JSON object — even ``{"agent_name": ..., "findings": []}`` — is a
    genuine subagent verdict and must NOT be overwritten by the stashed-report
    recovery. Only prose/empty/garbage content (json.loads fails) qualifies for
    recovery.
    """
    if not content:
        return False
    text = content.content if hasattr(content, "content") else str(content)
    try:
        return isinstance(json.loads(_extract_json(text)), dict)
    except (TypeError, ValueError):
        return False


def _extract_per_agent(messages, capture: CaptureStore) -> list[AgentOutput]:
    task_calls = _index_task_calls(messages)
    outputs: list[AgentOutput] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        agent_name = task_calls.get(msg.tool_call_id)
        if agent_name is None:
            continue
        output = _parse_tool_message(agent_name, msg.content)
        if output.findings:
            outputs.append(output)
            continue
        if _looks_like_json_obj(msg.content):
            outputs.append(output)
            continue
        # Final message was prose/empty — the model likely emitted its real
        # report in an earlier message that the middleware stashed. Recover it.
        stashed = capture.consume_report(agent_name)
        if stashed is not None:
            try:
                report = _coerce_report(json.dumps(stashed), agent_name)
                outputs.append(_to_agent_output(report))
                continue
            except Exception:
                logger.warning("Could not coerce stashed report for %s", agent_name)
        outputs.append(output)
    return outputs


def _truncate(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


async def _emit_events(messages) -> None:
    task_calls = _index_task_calls(messages)
    for msg in messages:
        if isinstance(msg, AIMessage):
            if msg.content:
                await log_event("thinking", agent="orchestrator", content=_truncate(str(msg.content)))
            for tc in msg.tool_calls or []:
                await log_event(
                    "tool_call",
                    agent="orchestrator",
                    tool=tc.get("name"),
                    input_=tc.get("args"),
                )
        elif isinstance(msg, ToolMessage):
            agent = task_calls.get(msg.tool_call_id, "orchestrator")
            await log_event(
                "tool_result",
                agent=agent,
                tool=msg.name or "task",
                output=_truncate(str(msg.content)),
            )
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            await log_event("final", content=_truncate(str(msg.content)))
            break
