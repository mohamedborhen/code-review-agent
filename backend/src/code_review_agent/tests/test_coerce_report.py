"""Tests for _coerce_report: handles Nemotron's [[{name, parameters}]] format.

Session-141 confirmed Nemotron outputs structured tool calls as:
  [[{"name":"SubagentReport","parameters":{...}}]]
rather than as a plain dict. _coerce_report must unwrap this format.
"""

import json

from infrastructure.agents_runtime.orchestrator_runtime import _coerce_report


def test_coerce_report_unwraps_list_with_subagent_report():
    """Nemotron format: [[{name, parameters}]] -> unwrapped."""
    payload = json.dumps([
        [{
            "name": "SubagentReport",
            "parameters": {
                "agent_name": "compliance",
                "findings": [{
                    "severity": "info",
                    "confidence": 0.9,
                    "title": "Test finding",
                    "description": "Description here",
                    "evidence": ["file.py:10"],
                    "recommendation": "Fix it",
                }],
            },
        }],
    ])
    result = _coerce_report(payload, "compliance")
    assert result.agent_name == "compliance"
    assert len(result.findings) == 1
    assert result.findings[0].title == "Test finding"


def test_coerce_report_unwraps_empty_parameters():
    """[[{name, parameters:{}}]] -> 0 findings."""
    payload = json.dumps([
        [{
            "name": "SubagentReport",
            "parameters": {},
        }],
    ])
    result = _coerce_report(payload, "security")
    assert result.agent_name == "security"
    assert len(result.findings) == 0


def test_coerce_report_handles_newlines_in_list():
    """[[\\n\\n]] -> empty report."""
    payload = "[[\n\n]]"
    result = _coerce_report(payload, "performance")
    assert result.agent_name == "performance"
    assert len(result.findings) == 0


def test_coerce_report_plain_dict_still_works():
    """Standard dict format still parsed correctly."""
    payload = json.dumps({
        "agent_name": "regression",
        "findings": [{
            "severity": "warning",
            "confidence": 0.7,
            "title": "Risk",
            "description": "Risk desc",
            "evidence": ["app.py:5"],
            "recommendation": "Check it",
        }],
    })
    result = _coerce_report(payload, "regression")
    assert result.agent_name == "regression"
    assert len(result.findings) == 1


def test_coerce_report_unknown_list_format_returns_empty():
    """[{"name":"X","parameters":{}}] -> empty (not SubagentReport)."""
    payload = json.dumps([{"name": "X", "parameters": {}}])
    result = _coerce_report(payload, "fix_suggestion")
    assert result.agent_name == "fix_suggestion"
    assert len(result.findings) == 0
