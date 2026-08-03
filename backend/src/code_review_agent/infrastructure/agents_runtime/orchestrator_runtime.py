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

import json
import logging
import re

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, ToolMessage

from domain.entities.agent_finding import AgentFinding, AgentInput, AgentOutput, ReviewResult
from infrastructure.agents_runtime.capture import CaptureStore
from infrastructure.agents_runtime.harness_profile import ensure_review_harness_profile
from infrastructure.agents_runtime.report_schema import FindingItem, SubagentReport
from infrastructure.agents_runtime.subagents.compliance_runtime import build_compliance_spec
from infrastructure.agents_runtime.subagents.fix_suggestion_runtime import build_fix_suggestion_spec
from infrastructure.agents_runtime.subagents.performance_runtime import build_performance_spec
from infrastructure.agents_runtime.subagents.regression_runtime import build_regression_spec
from infrastructure.agents_runtime.subagents.security_runtime import build_security_spec
from infrastructure.agents_runtime.tool_scoping import load_prompt
from infrastructure.config import settings
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


class OrchestratorRuntime:
    """Builds and runs the deep agent (orchestrator + aggregator in one)."""

    def __init__(self, mcp_client) -> None:
        self._mcp_client = mcp_client
        self.capture = CaptureStore()

    async def run_review(self, review_input: AgentInput, agent_names: list[str]) -> ReviewResult:
        ensure_review_harness_profile()

        subagent_specs = []
        if agent_names:
            for name in _ALL_SUBAGENTS:
                subagent_specs.append(await _SUBAGENT_BUILDERS[name](self._mcp_client, self.capture))

        system_prompt = load_prompt("orchestrator") + "\n\n" + load_prompt("aggregator")
        user_message = _build_user_message(review_input, agent_names)

        agent = create_deep_agent(
            model=settings.review_model,
            system_prompt=system_prompt,
            subagents=subagent_specs or None,
            response_format=SubagentReport,
        )

        result = await _run_with_retry(agent, user_message)
        messages = result.get("messages", [])

        await _emit_events(messages)

        return ReviewResult(
            aggregated=_parse_aggregated(result),
            per_agent=_extract_per_agent(messages),
        )


def _build_user_message(review_input: AgentInput, agent_names: list[str]) -> str:
    required = ", ".join(agent_names) if agent_names else "(none — answer directly)"
    lines = [
        f"Request type: {review_input.request_type}",
        f"Repo: {review_input.repo_id}",
        f"Graph commit hash: {review_input.graph_commit_hash}",
        f"Repo root (local path): {review_input.repo_root}",
        "",
        "Required subagents for this request type (you MUST delegate to each):",
        required,
        "",
        "Diff:",
        review_input.diff_content or "(no diff provided)",
        "",
        "Classify the request, delegate to every required subagent, then synthesize all "
        "reports into a single SubagentReport JSON.",
    ]
    return "\n".join(lines)


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
    if isinstance(structured, dict):
        try:
            report = SubagentReport.model_validate(structured)
            return AgentOutput(agent_name="aggregator", findings=_to_agent_output(report).findings)
        except Exception:
            pass
        try:
            report = _coerce_report(json.dumps(structured), "aggregator")
            report.agent_name = "aggregator"
            return AgentOutput(agent_name="aggregator", findings=_to_agent_output(report).findings)
        except Exception:
            logger.warning("Aggregator structured response did not match SubagentReport schema")
    logger.warning("No structured_response in orchestrator result; returning empty aggregated output")
    return AgentOutput(agent_name="aggregator")


def _parse_tool_message(agent_name: str, content) -> AgentOutput:
    if not content:
        return AgentOutput(agent_name=agent_name)
    text = content.content if hasattr(content, "content") else str(content)
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


async def _run_with_retry(agent, user_message: str, attempts: int = 2) -> dict:
    """Run the deep agent, retrying once on transient structured-output failures.

    The configured review model occasionally returns an empty/invalid native
    structured output (a weak-model failure mode observed during E2E), which
    deepagents surfaces as a parse error inside ``ainvoke``. That is transient
    and not a code defect, so retry before falling through to the 500 boundary.
    Unrelated exceptions propagate immediately.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await agent.ainvoke({"messages": [{"role": "user", "content": user_message}]})
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch for retry classification
            last = exc
            if not _STRUCTURED_OUTPUT_FAILURE.search(str(exc)):
                raise
            if attempt < attempts:
                logger.warning("Transient structured-output failure (attempt %s/%s): %s", attempt, attempts, exc)
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

    evidence: list[str] = []
    for e in item.get("evidence") or []:
        if isinstance(e, str):
            evidence.append(e)
        else:
            evidence.append(json.dumps(e, ensure_ascii=False, default=str))

    return FindingItem(
        severity=str(item.get("severity", "info")).lower(),
        confidence=confidence,
        title=str(item.get("title") or item.get("id") or ""),
        description=str(item.get("description", "")),
        evidence=evidence,
        recommendation=str(item.get("recommendation", "")),
    )


def _coerce_report(text: str, agent_name: str) -> SubagentReport:
    raw = json.loads(text)
    if not isinstance(raw, dict):
        return SubagentReport(agent_name=agent_name)
    findings_raw = raw.get("findings") or raw.get("violations") or []
    findings = [
        _coerce_finding(item)
        for item in findings_raw
        if isinstance(item, dict)
    ]
    return SubagentReport(
        agent_name=str(raw.get("agent_name") or agent_name),
        findings=findings,
    )


def _extract_per_agent(messages) -> list[AgentOutput]:
    task_calls = _index_task_calls(messages)
    outputs: list[AgentOutput] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        agent_name = task_calls.get(msg.tool_call_id)
        if agent_name is None:
            continue
        outputs.append(_parse_tool_message(agent_name, msg.content))
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
