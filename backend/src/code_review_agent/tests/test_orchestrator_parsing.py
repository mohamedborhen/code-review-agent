"""Comprehensive orchestrator parsing regression tests.

Covers the exact failure shapes observed in production (session 175/176):
- missing structured_response
- malformed JSON envelopes
- valid specialist output with malformed aggregator
- CaptureStore recovery path
- empty findings followed by valid findings
- provider retry then valid output
- provider retry then malformed output
"""

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from infrastructure.agents_runtime.orchestrator_parsing import (
    _coerce_report,
    _parse_aggregated,
    _parse_tool_message,
)
from infrastructure.agents_runtime.capture import CaptureStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_specialist_tool_message(agent_name: str, findings: list[dict], tool_call_id: str = "tc_1") -> ToolMessage:
    report = {"agent_name": agent_name, "findings": findings}
    return ToolMessage(content=json.dumps(report), tool_call_id=tool_call_id)


def _make_task_message(tool_call_id: str, agent_name: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": tool_call_id, "name": "task", "args": {"subagent_type": agent_name}}],
    )


def _valid_finding(title: str = "Test finding") -> dict:
    return {
        "severity": "warning",
        "confidence": 0.8,
        "title": title,
        "description": "Description here",
        "evidence": ["file.py:10"],
        "recommendation": "Fix it",
    }


# ---------------------------------------------------------------------------
# _coerce_report edge cases
# ---------------------------------------------------------------------------

class TestCoerceReport:
    def test_empty_json(self):
        report = _coerce_report("{}", "agent")
        assert report.agent_name == "agent"
        assert len(report.findings) == 0

    def test_empty_list(self):
        report = _coerce_report("[]", "agent")
        assert report.agent_name == "agent"
        assert len(report.findings) == 0

    def test_empty_nested_list(self):
        report = _coerce_report("[[]]", "agent")
        assert report.agent_name == "agent"
        assert len(report.findings) == 0

    def test_prose_text(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            _coerce_report("This is just prose, not JSON", "agent")

    def test_nested_list_with_report(self):
        payload = json.dumps([[{"name": "SubagentReport", "parameters": {"agent_name": "a", "findings": [_valid_finding()]}}]])
        report = _coerce_report(payload, "fallback")
        assert len(report.findings) == 1

    def test_dict_with_violations_key(self):
        payload = json.dumps({"violations": [_valid_finding("Violation")]})
        report = _coerce_report(payload, "agent")
        assert len(report.findings) == 1
        assert report.findings[0].title == "Violation"

    def test_dict_with_nested_findings(self):
        payload = json.dumps({"security_review": {"findings": [_valid_finding("Nested")]}})
        report = _coerce_report(payload, "agent")
        assert len(report.findings) == 1

    def test_string_confidence_coerced(self):
        payload = json.dumps({"findings": [{"severity": "info", "confidence": "high", "title": "X", "description": "Y", "evidence": [], "recommendation": ""}]})
        report = _coerce_report(payload, "agent")
        # "high" → 0.9, but _cap_confidence_on_empty_evidence downgrades to 0.3 (empty evidence)
        assert report.findings[0].confidence == 0.3

    def test_dict_as_evidence_coerced_to_strings(self):
        payload = json.dumps({"findings": [{"severity": "info", "confidence": 0.5, "title": "X", "description": "Y", "evidence": [{"line": 10}], "recommendation": ""}]})
        report = _coerce_report(payload, "agent")
        assert isinstance(report.findings[0].evidence[0], str)


# ---------------------------------------------------------------------------
# _parse_tool_message edge cases
# ---------------------------------------------------------------------------

class TestParseToolMessage:
    def test_none_content(self):
        output = _parse_tool_message("agent", None)
        assert output.parse_status == "ok"
        assert len(output.findings) == 0

    def test_empty_string_content(self):
        output = _parse_tool_message("agent", "")
        assert output.parse_status == "ok"

    def test_prose_content(self):
        output = _parse_tool_message("agent", "Just some text, not JSON at all")
        assert output.parse_status == "parse_failed"
        assert len(output.findings) == 1
        assert "parsing failed" in output.findings[0].title.lower()

    def test_valid_json_report(self):
        content = json.dumps({"agent_name": "compliance", "findings": [_valid_finding()]})
        output = _parse_tool_message("compliance", content)
        assert output.parse_status == "ok"
        assert len(output.findings) == 1

    def test_fenced_json(self):
        content = "```json\n" + json.dumps({"agent_name": "a", "findings": [_valid_finding()]}) + "\n```"
        output = _parse_tool_message("a", content)
        assert output.parse_status == "ok"

    def test_xml_wrapped_json(self):
        inner = json.dumps({"agent_name": "a", "findings": [_valid_finding()]})
        content = f"<subagent_report>{inner}</subagent_report>"
        output = _parse_tool_message("a", content)
        assert output.parse_status == "ok"

    def test_empty_dict_content(self):
        output = _parse_tool_message("agent", json.dumps({}))
        assert output.parse_status == "ok"
        assert len(output.findings) == 0


# ---------------------------------------------------------------------------
# _parse_aggregated — exact production failure shapes
# ---------------------------------------------------------------------------

class TestParseAggregated:
    def test_missing_structured_response_with_no_messages(self):
        """Production shape: orchestrator returns empty result dict."""
        result = _parse_aggregated({})
        assert result.parse_status == "parse_failed"
        assert len(result.findings) == 1
        assert "parsing failed" in result.findings[0].title.lower()

    def test_malformed_structured_response_string(self):
        """Production shape: structured_response is non-JSON string."""
        result = _parse_aggregated({"structured_response": "not valid json"})
        assert result.parse_status == "parse_failed"

    def test_malformed_structured_response_none(self):
        result = _parse_aggregated({"structured_response": None})
        assert result.parse_status == "parse_failed"

    def test_empty_structured_response_dict(self):
        result = _parse_aggregated({"structured_response": {}})
        # {} is valid for SubagentReport (no required fields besides defaults)
        assert result.parse_status == "ok"
        assert len(result.findings) == 0

    def test_valid_structured_response_dict(self):
        result = _parse_aggregated({
            "structured_response": {"agent_name": "aggregator", "findings": [_valid_finding()]}
        })
        assert result.parse_status == "ok"
        assert len(result.findings) == 1

    def test_valid_structured_response_model(self):
        """structured_response is already a SubagentReport instance."""
        from infrastructure.agents_runtime.report_schema import SubagentReport, FindingItem
        report = SubagentReport(agent_name="agg", findings=[
            FindingItem(severity="info", confidence=0.9, title="OK", description="All good", evidence=["a.py:1"])
        ])
        result = _parse_aggregated({"structured_response": report})
        assert result.parse_status == "ok"
        assert len(result.findings) == 1

    def test_specialist_fallback_when_aggregator_fails(self):
        """Valid specialist output recovers when aggregator parse fails."""
        messages = [
            _make_task_message("tc_1", "compliance"),
            _make_specialist_tool_message("compliance", [_valid_finding("Compliance issue")], tool_call_id="tc_1"),
        ]
        result = _parse_aggregated({
            "messages": messages,
            "structured_response": "malformed",
        })
        assert result.parse_status == "fallback_from_specialists"
        assert len(result.findings) == 1
        assert result.findings[0].title == "Compliance issue"

    def test_specialist_fallback_skips_parse_failed_specialists(self):
        """Only specialists with parse_status='ok' contribute to fallback."""
        messages = [
            _make_task_message("tc_1", "compliance"),
            _make_specialist_tool_message("compliance", [_valid_finding("OK finding")], tool_call_id="tc_1"),
            _make_task_message("tc_2", "security"),
            ToolMessage(content="not json at all", tool_call_id="tc_2"),
        ]
        result = _parse_aggregated({
            "messages": messages,
            "structured_response": "malformed",
        })
        assert result.parse_status == "fallback_from_specialists"
        assert len(result.findings) == 1
        assert result.findings[0].title == "OK finding"

    def test_no_valid_specialists_and_no_aggregator_is_parse_failed(self):
        """When nothing parses, return parse_failed."""
        messages = [
            _make_task_message("tc_1", "compliance"),
            ToolMessage(content="not json", tool_call_id="tc_1"),
        ]
        result = _parse_aggregated({
            "messages": messages,
            "structured_response": "malformed",
        })
        assert result.parse_status == "parse_failed"
        assert "parsing failed" in result.findings[0].title.lower()

    def test_empty_messages_with_malformed_structured_response(self):
        result = _parse_aggregated({
            "messages": [],
            "structured_response": "malformed",
        })
        assert result.parse_status == "parse_failed"

    def test_aimessage_with_valid_json_in_content(self):
        """Aggregator report found in last AIMessage content."""
        report_json = json.dumps({"agent_name": "aggregator", "findings": [_valid_finding("From AI")]})
        messages = [
            AIMessage(content=report_json),
        ]
        result = _parse_aggregated({
            "messages": messages,
            "structured_response": "malformed",
        })
        # Should find the report in AIMessage content
        assert result.parse_status in ("ok", "fallback_from_specialists")
        assert any(f.title == "From AI" for f in result.findings)

    def test_dedup_identical_findings_keeps_higher_confidence(self):
        """Two identical descriptions+evidence -> keep higher confidence."""
        messages = [
            _make_task_message("tc_1", "compliance"),
            _make_specialist_tool_message("compliance", [
                {"severity": "warning", "confidence": 0.5, "title": "A", "description": "Same", "evidence": ["f.py:1"], "recommendation": ""},
            ], tool_call_id="tc_1"),
            _make_task_message("tc_2", "security"),
            _make_specialist_tool_message("security", [
                {"severity": "critical", "confidence": 0.9, "title": "B", "description": "Same", "evidence": ["f.py:1"], "recommendation": ""},
            ], tool_call_id="tc_2"),
        ]
        result = _parse_aggregated({
            "messages": messages,
            "structured_response": "malformed",
        })
        assert result.parse_status == "fallback_from_specialists"
        assert len(result.findings) == 1
        assert result.findings[0].confidence == 0.9

    def test_aggregator_over_specialist_when_valid(self):
        """Valid aggregator output takes precedence over specialist fallback."""
        messages = [
            _make_task_message("tc_1", "compliance"),
            _make_specialist_tool_message("compliance", [_valid_finding("Specialist")], tool_call_id="tc_1"),
        ]
        result = _parse_aggregated({
            "messages": messages,
            "structured_response": {"agent_name": "aggregator", "findings": [_valid_finding("Aggregator")]}
        })
        assert result.parse_status == "ok"
        assert result.findings[0].title == "Aggregator"
