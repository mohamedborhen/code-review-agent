"""Tests for the split orchestrator modules (Task 3).

Imports target the new module paths so these tests go RED before the modules
are created, then GREEN once orchestrator_parsing / orchestrator_message /
orchestrator_retry / orchestrator_emit exist and re-export the expected names.
"""

import json

from domain.entities.agent_finding import AgentFinding, AgentOutput
from infrastructure.agents_runtime.report_schema import SubagentReport


# ── _coerce_report (from orchestrator_parsing) ──────────────────────────────


class TestCoerceReport:
    def test_plain_dict_with_findings(self):
        from infrastructure.agents_runtime.orchestrator_parsing import _coerce_report

        payload = json.dumps({
            "agent_name": "security",
            "findings": [
                {
                    "severity": "warning",
                    "confidence": 0.8,
                    "title": "Hardcoded key",
                    "description": "API key found in source",
                    "evidence": ["config.py:12"],
                    "recommendation": "Use env var",
                }
            ],
        })
        report = _coerce_report(payload, "security")
        assert report.agent_name == "security"
        assert len(report.findings) == 1
        assert report.findings[0].title == "Hardcoded key"

    def test_nemotron_list_format(self):
        from infrastructure.agents_runtime.orchestrator_parsing import _coerce_report

        payload = json.dumps([
            [{"name": "SubagentReport", "parameters": {
                "agent_name": "compliance",
                "findings": [
                    {
                        "severity": "critical",
                        "confidence": 1.0,
                        "title": "XSS",
                        "description": "User input not escaped",
                        "evidence": ["views.py:45"],
                        "recommendation": "Escape output",
                    }
                ],
            }}]
        ])
        report = _coerce_report(payload, "compliance")
        assert report.agent_name == "compliance"
        assert len(report.findings) == 1

    def test_empty_findings(self):
        from infrastructure.agents_runtime.orchestrator_parsing import _coerce_report

        payload = json.dumps({"agent_name": "regression", "findings": []})
        report = _coerce_report(payload, "regression")
        assert report.agent_name == "regression"
        assert report.findings == []


# ── _enforce_evidence_discipline (from orchestrator_parsing) ────────────────


class TestEnforceEvidenceDiscipline:
    def test_caps_confidence_on_empty_evidence(self):
        from infrastructure.agents_runtime.orchestrator_parsing import _enforce_evidence_discipline

        output = AgentOutput(
            agent_name="test",
            findings=[
                AgentFinding(
                    severity="warning",
                    confidence=0.9,
                    title="No evidence",
                    description="Finding with no evidence",
                    evidence=[],
                    recommendation="Check",
                )
            ],
        )
        result = _enforce_evidence_discipline(output)
        assert result.findings[0].confidence <= 0.3
        assert result.findings[0].title.startswith("(unverified)")

    def test_preserves_confidence_when_evidence_present(self):
        from infrastructure.agents_runtime.orchestrator_parsing import _enforce_evidence_discipline

        output = AgentOutput(
            agent_name="test",
            findings=[
                AgentFinding(
                    severity="warning",
                    confidence=0.9,
                    title="Has evidence",
                    description="Finding with evidence",
                    evidence=["file.py:10"],
                    recommendation="Check",
                )
            ],
        )
        result = _enforce_evidence_discipline(output)
        assert result.findings[0].confidence == 0.9

    def test_no_double_prefix(self):
        from infrastructure.agents_runtime.orchestrator_parsing import _enforce_evidence_discipline

        output = AgentOutput(
            agent_name="test",
            findings=[
                AgentFinding(
                    severity="info",
                    confidence=0.8,
                    title="(unverified) already",
                    description="Desc",
                    evidence=[],
                    recommendation="Fix",
                )
            ],
        )
        result = _enforce_evidence_discipline(output)
        assert result.findings[0].title == "(unverified) already"


# ── _build_user_message (from orchestrator_message) ─────────────────────────


class TestBuildUserMessage:
    def _make_input(self, **overrides):
        from domain.entities.agent_finding import AgentInput

        defaults = dict(
            request_type="review",
            diff_content="diff --git a/f.py b/f.py\n+pass",
            repo_id="owner/repo",
            repo_root="/tmp/repo",
            graph_commit_hash="abc123",
            question=None,
            conversation_id=None,
            user_id="u1",
        )
        defaults.update(overrides)
        return AgentInput(**defaults)

    def test_review_request_includes_required_agents(self):
        from infrastructure.agents_runtime.orchestrator_message import _build_user_message

        msg = _build_user_message(self._make_input(), ["compliance", "security"])
        assert "compliance" in msg
        assert "security" in msg

    def test_any_question_does_not_include_required_keyword(self):
        from infrastructure.agents_runtime.orchestrator_message import _build_user_message

        msg = _build_user_message(
            self._make_input(request_type="any_question", question="Is this safe?"),
            ["compliance"],
        )
        assert "Required subagents" not in msg
        assert "Available subagents" in msg

    def test_question_included_for_question_carrying_type(self):
        from infrastructure.agents_runtime.orchestrator_message import _build_user_message

        msg = _build_user_message(
            self._make_input(request_type="compliance_question", question="Check X"),
            ["compliance"],
        )
        assert "Check X" in msg

    def test_conversation_block_appended_when_context_available(self):
        from infrastructure.agents_runtime.orchestrator_message import _build_user_message

        msg = _build_user_message(
            self._make_input(conversation_id=42),
            ["compliance"],
            context_available=True,
        )
        assert "Historical conversation context is AVAILABLE" in msg

    def test_no_conversation_block_when_context_unavailable(self):
        from infrastructure.agents_runtime.orchestrator_message import _build_user_message

        msg = _build_user_message(
            self._make_input(conversation_id=42),
            ["compliance"],
            context_available=False,
        )
        assert "Historical conversation context" not in msg


# ── _truncate (from utils — verify still accessible) ────────────────────────


class TestTruncate:
    def test_short_unchanged(self):
        from infrastructure.agents_runtime.utils import truncate

        assert truncate("abc", limit=10) == "abc"

    def test_long_truncated(self):
        from infrastructure.agents_runtime.utils import truncate

        result = truncate("x" * 3000)
        assert len(result) < 3000
        assert result.endswith("...(truncated)")
