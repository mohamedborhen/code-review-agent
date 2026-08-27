"""Tests for the Nemotron stringified-findings fix.

The root cause of parse_failed: NVIDIA Nemotron serializes ``findings`` as a
JSON string (``"[{...}]"``) instead of a JSON array. Deepagents rejects this,
causing ``structured_response`` to be ``None``. These tests verify the repair
path handles this and all related edge cases.
"""

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from infrastructure.agents_runtime.orchestrator_parsing import (
    _coerce_report,
    _extract_text_from_content,
    _extract_report_from_failed_tool_calls,
    _parse_aggregated,
    _parse_tool_message,
    _repair_stringified_findings,
)


# ---------------------------------------------------------------------------
# _extract_text_from_content
# ---------------------------------------------------------------------------

class TestExtractTextFromContent:
    def test_plain_string(self):
        assert _extract_text_from_content("hello") == "hello"

    def test_none(self):
        assert _extract_text_from_content(None) == ""

    def test_list_of_text_blocks(self):
        content = [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": "world"},
        ]
        assert _extract_text_from_content(content) == "hello\nworld"

    def test_list_with_non_text_items(self):
        content = [
            {"type": "image", "url": "http://example.com/img.png"},
            {"type": "text", "text": "actual content"},
        ]
        result = _extract_text_from_content(content)
        assert "actual content" in result

    def test_object_with_content_attr(self):
        class FakeContent:
            content = "inner text"
        assert _extract_text_from_content(FakeContent()) == "inner text"

    def test_dict_with_text_key(self):
        # A plain dict falls through to str() — this is expected behavior
        # The function handles list content blocks, not arbitrary dicts
        result = _extract_text_from_content({"text": "hello"})
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _repair_stringified_findings
# ---------------------------------------------------------------------------

class TestRepairStringifiedFindings:
    def test_no_repair_needed(self):
        raw = {"agent_name": "a", "findings": [{"severity": "info", "confidence": 0.5, "title": "X", "description": "Y", "evidence": [], "recommendation": ""}]}
        repaired = _repair_stringified_findings(raw)
        assert isinstance(repaired["findings"], list)

    def test_stringified_findings_repaired(self):
        findings_list = [{"severity": "warning", "confidence": 0.8, "title": "X", "description": "Y", "evidence": ["f.py:1"], "recommendation": "Fix"}]
        raw = {"agent_name": "a", "findings": json.dumps(findings_list)}
        repaired = _repair_stringified_findings(raw)
        assert isinstance(repaired["findings"], list)
        assert len(repaired["findings"]) == 1
        assert repaired["findings"][0]["title"] == "X"

    def test_stringified_findings_invalid_json(self):
        raw = {"agent_name": "a", "findings": "not valid json"}
        repaired = _repair_stringified_findings(raw)
        assert repaired["findings"] == "not valid json"

    def test_stringified_findings_not_a_list(self):
        raw = {"agent_name": "a", "findings": '{"key": "value"}'}
        repaired = _repair_stringified_findings(raw)
        assert repaired["findings"] == '{"key": "value"}'

    def test_non_dict_input(self):
        assert _repair_stringified_findings("string") == "string"
        assert _repair_stringified_findings(None) is None

    def test_preserves_other_keys(self):
        raw = {"agent_name": "test", "findings": "[{\"severity\": \"info\", \"confidence\": 0.5, \"title\": \"X\", \"description\": \"Y\", \"evidence\": [], \"recommendation\": \"\"}]", "extra": 42}
        repaired = _repair_stringified_findings(raw)
        assert repaired["extra"] == 42
        assert isinstance(repaired["findings"], list)


# ---------------------------------------------------------------------------
# _extract_report_from_failed_tool_calls
# ---------------------------------------------------------------------------

class TestExtractReportFromFailedToolCalls:
    def test_recovers_from_nemotron_stringified_findings(self):
        """Simulates the exact Nemotron failure: findings as a string in tool call args."""
        findings_list = [{"severity": "warning", "confidence": 0.8, "title": "Resource leak", "description": "File not deleted", "evidence": ["app.py:42"], "recommendation": "Use try-finally"}]
        messages = [
            AIMessage(content="", tool_calls=[{
                "id": "tc_agg", "name": "SubagentReport",
                "args": {"agent_name": "aggregator", "findings": json.dumps(findings_list)},
            }]),
        ]
        report = _extract_report_from_failed_tool_calls(messages)
        assert report is not None
        assert report.agent_name == "aggregator"
        assert len(report.findings) == 1
        assert report.findings[0].title == "Resource leak"

    def test_no_subagent_report_tool_calls(self):
        messages = [
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "task", "args": {"subagent_type": "security"}}]),
        ]
        assert _extract_report_from_failed_tool_calls(messages) is None

    def test_empty_messages(self):
        assert _extract_report_from_failed_tool_calls([]) is None

    def test_empty_tool_calls(self):
        messages = [
            AIMessage(content="", tool_calls=[]),
        ]
        assert _extract_report_from_failed_tool_calls(messages) is None

    def test_valid_findings_in_args(self):
        """When findings is already a list (not stringified), still recovers."""
        findings_list = [{"severity": "info", "confidence": 0.9, "title": "OK", "description": "All good", "evidence": ["a.py:1"], "recommendation": "None"}]
        messages = [
            AIMessage(content="", tool_calls=[{
                "id": "tc_agg", "name": "SubagentReport",
                "args": {"agent_name": "aggregator", "findings": findings_list},
            }]),
        ]
        report = _extract_report_from_failed_tool_calls(messages)
        assert report is not None
        assert len(report.findings) == 1


# ---------------------------------------------------------------------------
# _parse_tool_message with content-block lists
# ---------------------------------------------------------------------------

class TestParseToolMessageContentBlocks:
    def test_plain_string_content(self):
        content = json.dumps({"agent_name": "compliance", "findings": [{"severity": "info", "confidence": 0.9, "title": "OK", "description": "All good", "evidence": ["a.py:1"], "recommendation": ""}]})
        output = _parse_tool_message("compliance", content)
        assert output.parse_status == "ok"
        assert len(output.findings) == 1

    def test_list_of_content_blocks(self):
        report_json = json.dumps({"agent_name": "security", "findings": [{"severity": "warning", "confidence": 0.8, "title": "Issue", "description": "Desc", "evidence": ["f.py:5"], "recommendation": "Fix"}]})
        content = [{"type": "text", "text": report_json}]
        output = _parse_tool_message("security", content)
        assert output.parse_status == "ok"
        assert len(output.findings) == 1

    def test_list_with_stringified_findings(self):
        """Nemotron may produce findings as a string even in subagent ToolMessages."""
        findings_str = json.dumps([{"severity": "critical", "confidence": 0.9, "title": "Secret", "description": "Hardcoded", "evidence": ["config.py:1"], "recommendation": "Remove"}])
        report = {"agent_name": "compliance", "findings": findings_str}
        content = [{"type": "text", "text": json.dumps(report)}]
        output = _parse_tool_message("compliance", content)
        assert output.parse_status == "ok"
        assert len(output.findings) == 1
        assert output.findings[0].title == "Secret"

    def test_empty_content(self):
        output = _parse_tool_message("agent", None)
        assert output.parse_status == "ok"
        assert len(output.findings) == 0


# ---------------------------------------------------------------------------
# _parse_aggregated with Nemotron failure pattern
# ---------------------------------------------------------------------------

class TestParseAggregatedNemotron:
    def test_structured_response_none_with_failed_tool_calls(self):
        """The exact Nemotron pattern: structured_response is None, but tool call args have the report."""
        findings_list = [{"severity": "warning", "confidence": 0.8, "title": "Leak", "description": "Temp file", "evidence": ["app.py:42"], "recommendation": "Fix"}]
        messages = [
            AIMessage(content="", tool_calls=[{
                "id": "tc_agg", "name": "SubagentReport",
                "args": {"agent_name": "aggregator", "findings": json.dumps(findings_list)},
            }]),
        ]
        result = _parse_aggregated({"messages": messages, "structured_response": None})
        assert result.parse_status == "ok"
        assert len(result.findings) == 1
        assert result.findings[0].title == "Leak"

    def test_structured_response_dict_with_stringified_findings(self):
        findings_list = [{"severity": "info", "confidence": 0.9, "title": "OK", "description": "All good", "evidence": ["a.py:1"], "recommendation": ""}]
        result = _parse_aggregated({
            "structured_response": {"agent_name": "agg", "findings": json.dumps(findings_list)},
        })
        assert result.parse_status == "ok"
        assert len(result.findings) == 1

    def test_structured_response_string(self):
        """Nemotron may emit the report as a JSON string in structured_response."""
        report = {"agent_name": "agg", "findings": [{"severity": "info", "confidence": 0.9, "title": "X", "description": "Y", "evidence": [], "recommendation": ""}]}
        result = _parse_aggregated({"structured_response": json.dumps(report)})
        assert result.parse_status == "ok"
        assert len(result.findings) == 1

    def test_specialist_fallback_with_content_blocks(self):
        """Specialist findings in ToolMessage with content-block list format."""
        findings = [{"severity": "warning", "confidence": 0.8, "title": "X", "description": "Y", "evidence": ["f.py:1"], "recommendation": "Fix"}]
        report_json = json.dumps({"agent_name": "security", "findings": findings})
        messages = [
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "task", "args": {"subagent_type": "security"}}]),
            ToolMessage(content=[{"type": "text", "text": report_json}], tool_call_id="tc_1"),
        ]
        result = _parse_aggregated({"messages": messages, "structured_response": None})
        assert result.parse_status == "fallback_from_specialists"
        assert len(result.findings) == 1

    def test_specialist_fallback_with_stringified_findings_in_content_block(self):
        """Nemotron stringified findings inside a content-block ToolMessage."""
        findings_str = json.dumps([{"severity": "high", "confidence": 0.7, "title": "Hardcoded key", "description": "API key in source", "evidence": ["config.py:5"], "recommendation": "Use env"}])
        report = {"agent_name": "compliance", "findings": findings_str}
        report_json = json.dumps(report)
        messages = [
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "task", "args": {"subagent_type": "compliance"}}]),
            ToolMessage(content=[{"type": "text", "text": report_json}], tool_call_id="tc_1"),
        ]
        result = _parse_aggregated({"messages": messages, "structured_response": None})
        assert result.parse_status == "fallback_from_specialists"
        assert len(result.findings) == 1
        assert result.findings[0].title == "Hardcoded key"
