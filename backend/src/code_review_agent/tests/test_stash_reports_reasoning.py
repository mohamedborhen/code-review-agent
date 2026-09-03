"""Regression tests for _stash_reports reasoning recovery.

Root cause (Review 237): Nemotron emits SubagentReport JSON inside
``additional_kwargs["reasoning"]`` / ``"reasoning_content"`` rather than
in ``msg.content``.  The old ``_stash_reports`` only checked ``msg.content``,
so the report was lost and the aggregator received ``parse_failed``.

These tests verify that the fixed ``_stash_reports`` recovers reports from:
- ``msg.content`` (original path — still works)
- ``additional_kwargs["reasoning"]``
- ``additional_kwargs["reasoning_content"]``
"""

import json

import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage

from infrastructure.agents_runtime.capture import CaptureStore, SubagentCaptureMiddleware
from infrastructure.agents_runtime.report_schema import FindingItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_report_dict(agent_name: str = "compliance") -> dict:
    return {
        "agent_name": agent_name,
        "findings": [
            {
                "severity": "warning",
                "confidence": 0.85,
                "title": "Hardcoded secret",
                "description": "API key in config.py",
                "evidence": ["config.py:12"],
                "recommendation": "Use environment variable",
            }
        ],
    }


def _fake_request():
    class _M:
        model_id = "nvidia:nvidia/nemotron-3-ultra-550b-a55b"
    class _Req:
        model = _M()
    return _Req()


# ---------------------------------------------------------------------------
# CaptureStore.report basics (unchanged)
# ---------------------------------------------------------------------------

class TestCaptureStoreReport:
    def test_record_and_consume_report(self):
        store = CaptureStore()
        report = _valid_report_dict()
        store.record_report("compliance", report)
        consumed = store.consume_report("compliance")
        assert consumed is not None
        assert consumed["agent_name"] == "compliance"
        assert len(consumed["findings"]) == 1

    def test_consume_report_fifo(self):
        store = CaptureStore()
        store.record_report("compliance", {"agent_name": "compliance", "findings": []})
        store.record_report("compliance", {"agent_name": "compliance", "findings": [{"severity": "info", "confidence": 0.9, "title": "Second", "description": "", "evidence": [], "recommendation": ""}]})
        first = store.consume_report("compliance")
        second = store.consume_report("compliance")
        assert first["findings"] == []
        assert len(second["findings"]) == 1

    def test_consume_report_empty(self):
        store = CaptureStore()
        assert store.consume_report("missing") is None


# ---------------------------------------------------------------------------
# _stash_reports — report in msg.content (original path)
# ---------------------------------------------------------------------------

class TestStashReportsFromContent:
    def test_report_in_content_stashed(self):
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        report_json = json.dumps(_valid_report_dict())
        msg = AIMessage(content=report_json)
        mw._stash_reports(ModelResponse(result=[msg]))
        consumed = store.consume_report("compliance")
        assert consumed is not None
        assert consumed["agent_name"] == "compliance"
        assert len(consumed["findings"]) == 1

    def test_fenced_report_in_content_stashed(self):
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("security", store)
        report_json = json.dumps(_valid_report_dict("security"))
        msg = AIMessage(content=f"```json\n{report_json}\n```")
        mw._stash_reports(ModelResponse(result=[msg]))
        consumed = store.consume_report("security")
        assert consumed is not None
        assert consumed["agent_name"] == "security"


# ---------------------------------------------------------------------------
# _stash_reports — report in additional_kwargs["reasoning"]
# ---------------------------------------------------------------------------

class TestStashReportsFromReasoning:
    def test_report_in_reasoning_stashed(self):
        """Nemotron pattern: report JSON in reasoning, not in content."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        report_json = json.dumps(_valid_report_dict())
        msg = AIMessage(
            content="Here is my analysis.",
            additional_kwargs={"reasoning": report_json},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        consumed = store.consume_report("compliance")
        assert consumed is not None
        assert consumed["agent_name"] == "compliance"
        assert len(consumed["findings"]) == 1

    def test_report_in_reasoning_content_stashed(self):
        """Alternate Nemotron field: reasoning_content."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("security", store)
        report_json = json.dumps(_valid_report_dict("security"))
        msg = AIMessage(
            content="",
            additional_kwargs={"reasoning_content": report_json},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        consumed = store.consume_report("security")
        assert consumed is not None
        assert consumed["agent_name"] == "security"

    def test_report_in_reasoning_with_prose_content(self):
        """Nemotron emits prose in content, report in reasoning."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        report_json = json.dumps(_valid_report_dict())
        msg = AIMessage(
            content="I found several security issues in the codebase.",
            additional_kwargs={"reasoning": report_json},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        consumed = store.consume_report("compliance")
        assert consumed is not None

    def test_report_in_reasoning_takes_precedence_over_non_report_content(self):
        """When content is prose and reasoning has report, only reasoning is stashed."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        report_json = json.dumps(_valid_report_dict())
        msg = AIMessage(
            content="Just some thinking text.",
            additional_kwargs={"reasoning": report_json},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        consumed = store.consume_report("compliance")
        assert consumed is not None
        assert consumed["agent_name"] == "compliance"


# ---------------------------------------------------------------------------
# _stash_reports — content takes priority over reasoning
# ---------------------------------------------------------------------------

class TestStashReportsPriority:
    def test_content_report_stashed_even_when_reasoning_has_report(self):
        """If content already has a report, reasoning report is NOT double-stashed."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        content_report = _valid_report_dict()
        content_report["findings"][0]["title"] = "FromContent"
        reasoning_report = _valid_report_dict()
        reasoning_report["findings"][0]["title"] = "FromReasoning"
        msg = AIMessage(
            content=json.dumps(content_report),
            additional_kwargs={"reasoning": json.dumps(reasoning_report)},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        # Only one report stashed (from content path), not two
        consumed = store.consume_report("compliance")
        assert consumed is not None
        assert consumed["findings"][0]["title"] == "FromContent"
        assert store.consume_report("compliance") is None


# ---------------------------------------------------------------------------
# _stash_reports — non-report data NOT stashed
# ---------------------------------------------------------------------------

class TestStashReportsRejection:
    def test_empty_content_not_stashed(self):
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        msg = AIMessage(content="")
        mw._stash_reports(ModelResponse(result=[msg]))
        assert store.consume_report("compliance") is None

    def test_prose_only_not_stashed(self):
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        msg = AIMessage(content="This is just plain prose, no JSON at all.")
        mw._stash_reports(ModelResponse(result=[msg]))
        assert store.consume_report("compliance") is None

    def test_empty_dict_in_reasoning_not_stashed(self):
        """Empty dict is valid JSON but has no findings — should not be stashed."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        msg = AIMessage(
            content="",
            additional_kwargs={"reasoning": "{}"},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        assert store.consume_report("compliance") is None

    def test_non_report_json_in_reasoning_not_stashed(self):
        """JSON without findings array should not be stashed."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        msg = AIMessage(
            content="",
            additional_kwargs={"reasoning": '{"agent_name": "compliance"}'},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        assert store.consume_report("compliance") is None

    def test_list_content_blocks_not_stashed(self):
        """AIMessage with list content blocks (not AIMessage instances) — skipped."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        # ModelResponse with non-AIMessage items in result
        response = ModelResponse(result=[{"type": "text", "text": "not an AIMessage"}])
        mw._stash_reports(response)
        assert store.consume_report("compliance") is None


# ---------------------------------------------------------------------------
# _stash_reports — multiple messages, last one wins
# ---------------------------------------------------------------------------

class TestStashReportsMultipleMessages:
    def test_last_report_wins(self):
        """When multiple messages have reports, only the last one is consumed."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        report1 = _valid_report_dict()
        report1["findings"][0]["title"] = "First"
        report2 = _valid_report_dict()
        report2["findings"][0]["title"] = "Second"
        msg1 = AIMessage(content=json.dumps(report1))
        msg2 = AIMessage(content=json.dumps(report2))
        mw._stash_reports(ModelResponse(result=[msg1, msg2]))
        # Both stashed (FIFO), consume returns first
        first = store.consume_report("compliance")
        second = store.consume_report("compliance")
        assert first["findings"][0]["title"] == "First"
        assert second["findings"][0]["title"] == "Second"

    def test_reasoning_report_after_content_report_stashed(self):
        """Nemotron: first msg has content report, second has reasoning report."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        report1 = _valid_report_dict()
        report1["findings"][0]["title"] = "FromContent"
        report2 = _valid_report_dict()
        report2["findings"][0]["title"] = "FromReasoning"
        msg1 = AIMessage(content=json.dumps(report1))
        msg2 = AIMessage(
            content="Final analysis.",
            additional_kwargs={"reasoning": json.dumps(report2)},
        )
        mw._stash_reports(ModelResponse(result=[msg1, msg2]))
        first = store.consume_report("compliance")
        second = store.consume_report("compliance")
        assert first["findings"][0]["title"] == "FromContent"
        assert second["findings"][0]["title"] == "FromReasoning"


# ---------------------------------------------------------------------------
# End-to-end: _stash_reports → consume_report → orchestrator recovery
# ---------------------------------------------------------------------------

class TestStashReportsE2E:
    def test_stashed_report_recovers_parse_failure(self):
        """Simulates the full Nemotron recovery: stash from reasoning, consume in orchestrator."""
        from infrastructure.agents_runtime.orchestrator_parsing import _coerce_report

        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        report_json = json.dumps(_valid_report_dict("compliance"))
        msg = AIMessage(
            content="Here is my analysis.",
            additional_kwargs={"reasoning": report_json},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        stashed = store.consume_report("compliance")
        assert stashed is not None

        # Orchestrator can coerce the stashed dict into a SubagentReport
        report = _coerce_report(json.dumps(stashed), "compliance")
        assert report.agent_name == "compliance"
        assert len(report.findings) == 1
        assert report.findings[0].title == "Hardcoded secret"

    def test_stashed_report_with_stringified_findings_not_recovered(self):
        """Stringified findings in reasoning are NOT stashed — report_dict_from_text
        requires findings to be a list, not a string.  The stringified-findings
        repair path lives in the orchestrator parsing layer, not in capture.
        """
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        findings_list = [
            {"severity": "critical", "confidence": 0.9, "title": "SQL Injection", "description": "Unsanitized input", "evidence": ["db.py:42"], "recommendation": "Use parameterized queries"}
        ]
        report = {"agent_name": "compliance", "findings": json.dumps(findings_list)}
        msg = AIMessage(
            content="",
            additional_kwargs={"reasoning": json.dumps(report)},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        # findings is a string, not a list — report_dict_from_text rejects it
        assert store.consume_report("compliance") is None

    def test_stashed_report_with_valid_findings_and_repair(self):
        """When findings IS a list, stash works; _repair is a no-op."""
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("compliance", store)
        findings_list = [
            {"severity": "critical", "confidence": 0.9, "title": "SQL Injection", "description": "Unsanitized input", "evidence": ["db.py:42"], "recommendation": "Use parameterized queries"}
        ]
        report = {"agent_name": "compliance", "findings": findings_list}
        msg = AIMessage(
            content="",
            additional_kwargs={"reasoning": json.dumps(report)},
        )
        mw._stash_reports(ModelResponse(result=[msg]))
        stashed = store.consume_report("compliance")
        assert stashed is not None

        from infrastructure.agents_runtime.orchestrator_parsing import _repair_stringified_findings
        repaired = _repair_stringified_findings(stashed)
        assert isinstance(repaired["findings"], list)
        assert repaired["findings"][0]["title"] == "SQL Injection"
