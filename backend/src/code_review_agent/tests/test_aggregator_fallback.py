"""Tests for Issue 4: Aggregator fallback — preserve specialist text when parsing fails.

When the aggregator's own output cannot be parsed, _parse_aggregated should
synthesize findings from specialist ToolMessages that parsed successfully.
"""

import json

from langchain_core.messages import AIMessage, ToolMessage

from infrastructure.agents_runtime.orchestrator_runtime import _parse_aggregated


def _make_specialist_tool_message(agent_name: str, findings: list[dict], tool_call_id: str = "tc_1") -> ToolMessage:
    """Create a ToolMessage with a SubagentReport-style JSON payload."""
    report = {
        "agent_name": agent_name,
        "findings": findings,
    }
    return ToolMessage(content=json.dumps(report), tool_call_id=tool_call_id)


def _make_task_message(tool_call_id: str, agent_name: str) -> AIMessage:
    """Create an AIMessage with a task tool call for the specialist."""
    return AIMessage(
        content="",
        tool_calls=[{"id": tool_call_id, "name": "task", "args": {"subagent_type": agent_name}}],
    )


def test_fallback_merges_ok_specialists_only():
    """When aggregator parse fails, only specialists with parse_status='ok' contribute."""
    # Build messages: one ok specialist, one parse_failed specialist
    messages = [
        _make_task_message("tc_1", "compliance"),
        _make_specialist_tool_message("compliance", [
            {"severity": "warning", "confidence": 0.8, "title": "Missing tests",
             "description": "No unit tests for new function", "evidence": ["app.py:42"],
             "recommendation": "Add tests"},
        ], tool_call_id="tc_1"),
        _make_task_message("tc_2", "security"),
        ToolMessage(content="this is not JSON at all", tool_call_id="tc_2"),  # parse_failed
    ]
    result = _parse_aggregated({
        "messages": messages,
        "structured_response": "not valid json",  # force aggregator parse failure
    })
    assert result.parse_status == "fallback_from_specialists"
    assert len(result.findings) == 1
    assert result.findings[0].title == "Missing tests"


def test_dedup_same_description_and_evidence_keeps_higher_confidence():
    """Two findings with identical description+evidence -> keep the one with higher confidence."""
    messages = [
        _make_task_message("tc_1", "compliance"),
        _make_specialist_tool_message("compliance", [
            {"severity": "warning", "confidence": 0.6, "title": "Finding A",
             "description": "Same description", "evidence": ["file.py:10"],
             "recommendation": "Fix A"},
        ], tool_call_id="tc_1"),
        _make_task_message("tc_2", "security"),
        _make_specialist_tool_message("security", [
            {"severity": "critical", "confidence": 0.9, "title": "Finding B",
             "description": "Same description", "evidence": ["file.py:10"],
             "recommendation": "Fix B"},
        ], tool_call_id="tc_2"),
    ]
    result = _parse_aggregated({
        "messages": messages,
        "structured_response": "not valid json",
    })
    assert result.parse_status == "fallback_from_specialists"
    assert len(result.findings) == 1
    assert result.findings[0].confidence == 0.9


def test_dedup_different_description_keeps_both():
    """Two distinct findings -> both kept."""
    messages = [
        _make_task_message("tc_1", "compliance"),
        _make_specialist_tool_message("compliance", [
            {"severity": "warning", "confidence": 0.8, "title": "Finding A",
             "description": "Description A", "evidence": ["file.py:10"],
             "recommendation": "Fix A"},
        ], tool_call_id="tc_1"),
        _make_task_message("tc_2", "security"),
        _make_specialist_tool_message("security", [
            {"severity": "critical", "confidence": 0.9, "title": "Finding B",
             "description": "Description B", "evidence": ["file.py:20"],
             "recommendation": "Fix B"},
        ], tool_call_id="tc_2"),
    ]
    result = _parse_aggregated({
        "messages": messages,
        "structured_response": "not valid json",
    })
    assert result.parse_status == "fallback_from_specialists"
    assert len(result.findings) == 2


def test_aggregator_parse_succeeds_no_fallback():
    """When aggregator parses successfully, no fallback is used."""
    result = _parse_aggregated({
        "structured_response": {
            "agent_name": "aggregator",
            "findings": [{"severity": "info", "confidence": 0.9, "title": "OK",
                          "description": "All good", "evidence": ["a.py:1"],
                          "recommendation": "None"}],
        },
    })
    assert result.parse_status == "ok"
    assert len(result.findings) == 1


def test_no_ok_specialists_with_findings_parse_failed():
    """When no specialist has parse_status='ok' with findings, parse_failed sentinel."""
    messages = [
        _make_task_message("tc_1", "compliance"),
        ToolMessage(content="not json", tool_call_id="tc_1"),
    ]
    result = _parse_aggregated({
        "messages": messages,
        "structured_response": "not valid json",
    })
    assert result.parse_status == "parse_failed"
    assert len(result.findings) == 1
    assert "parsing failed" in result.findings[0].title.lower()
