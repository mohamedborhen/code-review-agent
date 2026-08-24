"""Parsing helpers extracted from orchestrator_runtime (Task 3).

Functions that coerce, validate, and parse SubagentReport / AgentOutput
from raw tool messages and structured responses.
"""

import hashlib
import json
import logging
import re

from langchain_core.messages import AIMessage, ToolMessage

from domain.entities.agent_finding import AgentFinding, AgentInput, AgentOutput
from infrastructure.agents_runtime.report_parse import extract_json_text as _extract_json
from infrastructure.agents_runtime.report_schema import FindingItem, SubagentReport
from infrastructure.agents_runtime.utils import findings_list as _findings_list

logger = logging.getLogger(__name__)


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


def _enforce_evidence_discipline(output: AgentOutput) -> AgentOutput:
    """Post-process findings: cap confidence on empty evidence, flag unverified.

    This is the programmatic backstop for the aggregator prompt's instruction
    to verify evidence.  The FindingItem pydantic validator handles schema-
    level enforcement; this function handles the domain-level AgentOutput
    after conversion from SubagentReport.
    """
    for f in output.findings:
        if not f.evidence and f.confidence > 0.5:
            f.confidence = min(f.confidence, 0.3)
            if not f.title.startswith("(unverified)"):
                f.title = f"(unverified) {f.title}"
    return output


_STRING_CONFIDENCE: dict[str, float] = {
    "low": 0.3,
    "medium": 0.6,
    "high": 0.9,
    "critical": 1.0,
}


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


def _coerce_report(text: str, agent_name: str) -> SubagentReport:
    raw = json.loads(text)
    if isinstance(raw, list):
        inner = raw
        while isinstance(inner, list) and len(inner) == 1:
            inner = inner[0]
        if (
            isinstance(inner, dict)
            and inner.get("name") == "SubagentReport"
            and isinstance(inner.get("parameters"), dict)
        ):
            raw = inner["parameters"]
        else:
            return SubagentReport(agent_name=agent_name)
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
        return AgentOutput(
            agent_name=agent_name,
            findings=[AgentFinding(
                severity="warning",
                confidence=0.0,
                title=f"{agent_name}: structured output parsing failed",
                description=(
                    "The subagent produced output that could not be parsed as a "
                    "SubagentReport. Review the raw tool output in the event log."
                ),
                evidence=["parse_status=parse_failed"],
                recommendation="Retry the review or inspect the subagent's raw output.",
            )],
            parse_status="parse_failed",
        )


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
    from_messages = _parse_aggregated_from_messages(result)
    if from_messages is not None and from_messages.findings:
        return from_messages
    if from_dict is not None:
        return from_dict
    if from_messages is not None:
        return from_messages
    messages = result.get("messages", [])
    if messages:
        task_calls = _index_task_calls(messages)
        specialist_outputs = []
        for msg in messages:
            if not isinstance(msg, ToolMessage):
                continue
            agent = task_calls.get(msg.tool_call_id)
            if agent and agent != "orchestrator":
                output = _parse_tool_message(agent, msg.content)
                if output.parse_status == "ok" and output.findings:
                    specialist_outputs.append(output)
        if specialist_outputs:
            all_findings = []
            for output in specialist_outputs:
                all_findings.extend(output.findings)
            seen: dict[str, AgentFinding] = {}
            for f in all_findings:
                first_evidence = f.evidence[0] if f.evidence else ""
                identity = hashlib.sha256(
                    f"{f.description}\x00{first_evidence}".encode()
                ).hexdigest()[:16]
                if identity not in seen or f.confidence > seen[identity].confidence:
                    seen[identity] = f
            deduped = list(seen.values())
            return AgentOutput(
                agent_name="aggregator",
                findings=deduped,
                parse_status="fallback_from_specialists",
            )
    logger.warning("No structured_response in orchestrator result; returning empty aggregated output")
    return AgentOutput(
        agent_name="aggregator",
        findings=[AgentFinding(
            severity="warning",
            confidence=0.0,
            title="Aggregator structured output parsing failed",
            description=(
                "The orchestrator's synthesis could not be parsed as a "
                "SubagentReport. The aggregated findings are unavailable."
            ),
            evidence=["parse_status=parse_failed"],
            recommendation="Retry the review.",
        )],
        parse_status="parse_failed",
    )


def _parse_aggregated_from_messages(result: dict) -> AgentOutput | None:
    """Parse the aggregator report from the last AIMessage content, if any."""
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


def _looks_like_json_obj(content) -> bool:
    """True when the final ToolMessage content is at least a JSON object."""
    if not content:
        return False
    text = content.content if hasattr(content, "content") else str(content)
    try:
        return isinstance(json.loads(_extract_json(text)), dict)
    except (TypeError, ValueError):
        return False
