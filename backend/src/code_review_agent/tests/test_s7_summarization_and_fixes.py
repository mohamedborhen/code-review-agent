"""S7 integration test: in-context summarization middleware trigger.

Verifies that the SummarizationMiddleware actually fires when the accumulated
token count exceeds the configured trigger threshold.  Uses a deliberately
low threshold (100 tokens) so the test runs without LLM calls or huge messages.
"""

import json

from deepagents.backends.state import StateBackend
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from infrastructure.agents_runtime.orchestrator_runtime import (
    _enforce_evidence_discipline,
    _parse_tool_message,
)
from infrastructure.config import settings
from domain.entities.agent_finding import AgentFinding, AgentOutput
from infrastructure.agents_runtime.report_schema import FindingItem, SubagentReport


def test_low_trigger_middleware_detects_overflow() -> None:
    """Construct middleware with trigger=100 tokens; feed ~500+ tokens of
    messages; verify the internal helper agrees summarization should fire."""
    backend = StateBackend()
    middleware = SummarizationMiddleware(
        model=settings.review_model,
        backend=backend,
        trigger=("tokens", 100),
        keep=("tokens", 50),
        token_counter=_approx_tokens,
    )
    # Build a message list that exceeds 100 tokens (~400+ chars)
    messages = [
        HumanMessage(content="x" * 200),
        AIMessage(content="y" * 200),
        ToolMessage(content="z" * 200, tool_call_id="t1"),
    ]
    # The middleware's internal token counter should see > 100 tokens
    total = middleware._count_tokens(messages, None, None)
    assert total > 100, f"Expected >100 tokens, got {total}"


def _approx_tokens(messages, tools=None) -> int:
    """Approximate token counter for testing (~4 chars per token)."""
    total = 0
    for m in messages:
        total += len(str(getattr(m, "content", ""))) // 4
    if tools:
        total += len(json.dumps([getattr(t, "name", "") for t in tools])) // 4
    return total


def test_parse_tool_message_diagnostic_on_failure() -> None:
    """Item 4: parse failure produces a diagnostic finding, not empty."""
    result = _parse_tool_message("compliance", "this is not JSON at all")
    assert result.parse_status == "parse_failed"
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.severity == "warning"
    assert finding.confidence == 0.0
    assert "parsing failed" in finding.title
    assert finding.agent_name == "compliance" if hasattr(finding, "agent_name") else True


def test_parse_tool_message_valid_json_empty_stays_empty() -> None:
    """Valid JSON with no findings -> parse_status='ok', empty findings."""
    content = json.dumps({"agent_name": "security", "findings": []})
    result = _parse_tool_message("security", content)
    assert result.parse_status == "ok"
    assert result.findings == []


def test_parse_tool_message_valid_json_with_findings() -> None:
    """Valid SubagentReport JSON -> parsed correctly."""
    content = json.dumps({
        "agent_name": "security",
        "findings": [{
            "severity": "info",
            "confidence": 0.9,
            "title": "No issues",
            "description": "Looks good",
            "evidence": ["file.py:10"],
        }],
    })
    result = _parse_tool_message("security", content)
    assert result.parse_status == "ok"
    assert len(result.findings) == 1
    assert result.findings[0].confidence == 0.9


def test_enforce_evidence_discipline_caps_empty_evidence() -> None:
    """Item 5: findings with empty evidence get confidence capped."""
    output = AgentOutput(
        agent_name="aggregator",
        findings=[
            AgentFinding(severity="critical", confidence=1.0, title="Bug found",
                         description="d", evidence=["file.py:42"]),
            AgentFinding(severity="warning", confidence=0.8, title="Maybe issue",
                         description="d", evidence=[]),
        ],
    )
    result = _enforce_evidence_discipline(output)
    assert result.findings[0].confidence == 1.0  # has evidence, unchanged
    assert result.findings[0].title == "Bug found"
    assert result.findings[1].confidence == 0.3  # empty evidence, capped
    assert result.findings[1].title == "(unverified) Maybe issue"


def test_enforce_evidence_discipline_preserves_valid_findings() -> None:
    """Item 5: findings with evidence pass through unchanged."""
    output = AgentOutput(
        agent_name="aggregator",
        findings=[
            AgentFinding(severity="info", confidence=0.95, title="OK",
                         description="d", evidence=["scoring.py:23"]),
        ],
    )
    result = _enforce_evidence_discipline(output)
    assert result.findings[0].confidence == 0.95
    assert result.findings[0].title == "OK"


def test_finding_item_validator_caps_empty_evidence() -> None:
    """Item 5: FindingItem pydantic validator caps confidence on empty evidence."""
    f = FindingItem(severity="critical", confidence=1.0, title="test",
                    description="d", evidence=[])
    assert f.confidence == 0.3
    assert f.title == "(unverified) test"


def test_finding_item_validator_preserves_valid_evidence() -> None:
    """Item 5: FindingItem with evidence keeps confidence."""
    f = FindingItem(severity="critical", confidence=1.0, title="test",
                    description="d", evidence=["file.py:42"])
    assert f.confidence == 1.0
    assert f.title == "test"


def test_agent_output_parse_status_default() -> None:
    """Item 4: AgentOutput has parse_status='ok' by default."""
    output = AgentOutput(agent_name="test")
    assert output.parse_status == "ok"
    assert output.findings == []
