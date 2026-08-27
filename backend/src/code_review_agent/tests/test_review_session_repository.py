"""Unit tests for ReviewSessionRepository — DB operations extracted from the
/review routes (Task 4).

Uses a temp SQLite engine (no live DB, no services), following the same
pattern as test_repo_workspace_repository.py.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlmodel import SQLModel, Session, create_engine, select

import infrastructure.db.models  # noqa: F401  (register tables on metadata)
import infrastructure.db.review_session_repository as repo_module
from domain.entities.agent_finding import AgentFinding, AgentOutput
from infrastructure.db.models import AgentExecution, ReviewSession, ReviewToolCall


class _FakeCapture:
    """Duck-typed CaptureStore stand-in — only consume_duration/consume_model used."""

    def __init__(self, models=None):
        self._durations = {"security": 250}
        self._models = (
            dict(models)
            if models is not None
            else {"security": "model-a", "orchestrator": "model-root"}
        )

    def consume_duration(self, agent_name: str) -> int:
        return self._durations.pop(agent_name, 0)

    def consume_model(self, agent_name: str) -> str | None:
        return self._models.get(agent_name)


def _per_agent(name: str = "security", confidence: float = 0.8) -> AgentOutput:
    return AgentOutput(
        agent_name=name,
        findings=[
            AgentFinding(
                severity="medium",
                confidence=confidence,
                title="t",
                description="d",
            )
        ],
    )


class ReviewSessionRepositoryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "test.db"
        self._engine = create_engine(f"sqlite:///{db_path}")
        SQLModel.metadata.create_all(self._engine)
        self._patcher = mock.patch.object(repo_module, "engine", self._engine)
        self._patcher.start()
        self.repo = repo_module.ReviewSessionRepository()

    def tearDown(self):
        self._patcher.stop()
        self._engine.dispose()
        self._tmp.cleanup()

    def _get_row(self, session_id: int) -> ReviewSession:
        with Session(self._engine) as s:
            return s.get(ReviewSession, session_id)

    # --- create -----------------------------------------------------------

    def test_create_returns_int_id_and_stores_user_id(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model="model-x",
            expected_agents=["security"],
            conversation_id=7,
            user_id="alice",
        )
        self.assertIsInstance(session_id, int)
        row = self._get_row(session_id)
        self.assertEqual(row.user_id, "alice")
        self.assertEqual(row.conversation_id, 7)
        self.assertEqual(row.status, "running")
        self.assertEqual(json.loads(row.expected_agents), ["security"])
        self.assertEqual(row.model, "model-x")

    def test_create_defaults_conversation_and_user_to_none(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model=None,
            expected_agents=[],
        )
        row = self._get_row(session_id)
        self.assertIsNone(row.user_id)
        self.assertIsNone(row.conversation_id)

    # --- get ---------------------------------------------------------------

    def test_get_returns_session_when_user_matches(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model=None,
            expected_agents=[],
            user_id="alice",
        )
        row = self.repo.get(session_id, "alice")
        self.assertIsNotNone(row)
        self.assertEqual(row.id, session_id)

    def test_get_returns_none_on_user_mismatch(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model=None,
            expected_agents=[],
            user_id="alice",
        )
        self.assertIsNone(self.repo.get(session_id, "bob"))

    def test_get_returns_none_for_nonexistent(self):
        self.assertIsNone(self.repo.get(999, "alice"))

    # --- find_running ------------------------------------------------------

    def _seed_running(self, **kwargs) -> int:
        defaults = dict(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model=None,
            expected_agents="[]",
            conversation_id=13,
            user_id="alice",
            status="running",
        )
        defaults.update(kwargs)
        with Session(self._engine) as s:
            row = ReviewSession(**defaults)
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def test_find_running_finds_running_review_with_user_enforcement(self):
        seeded = self._seed_running()
        row = self.repo.find_running(13, "alice")
        self.assertIsNotNone(row)
        self.assertEqual(row.id, seeded)
        self.assertIsNone(self.repo.find_running(13, "bob"))
        self.assertIsNone(self.repo.find_running(99, "alice"))

    def test_find_running_returns_none_for_completed_review(self):
        self._seed_running(status="completed")
        self.assertIsNone(self.repo.find_running(13, "alice"))

    # --- mark_completed / mark_failed --------------------------------------

    def test_mark_completed_updates_session(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model=None,
            expected_agents=[],
            user_id="alice",
        )
        self.repo.mark_completed(
            session_id, duration_ms=1234, dispatched_agents=["security"]
        )
        row = self._get_row(session_id)
        self.assertEqual(row.status, "completed")
        self.assertEqual(row.duration_ms, 1234)
        self.assertIsNotNone(row.completed_at)
        self.assertEqual(json.loads(row.dispatched_agents), ["security"])

    def test_mark_completed_missing_session_is_noop(self):
        self.repo.mark_completed(999, duration_ms=1, dispatched_agents=[])  # must not raise

    def test_mark_failed_sets_status_error_and_error_execution(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model=None,
            expected_agents=[],
            user_id="alice",
        )
        self.repo.mark_failed(session_id, RuntimeError("boom"))
        row = self._get_row(session_id)
        self.assertEqual(row.status, "failed")
        self.assertIn("boom", row.error)
        with Session(self._engine) as s:
            exec_row = s.exec(
                select(AgentExecution).where(
                    AgentExecution.review_session_id == session_id
                )
            ).first()
        self.assertIsNotNone(exec_row)
        self.assertEqual(exec_row.agent_name, "orchestrator")
        payload = json.loads(exec_row.result)
        self.assertEqual(payload["status"], "error")

    # --- record_executions --------------------------------------------------

    def test_record_executions_writes_rows_and_completes_session(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model="model-x",
            expected_agents=["security"],
            user_id="alice",
        )
        capture = _FakeCapture()
        aggregated = _per_agent("aggregator", confidence=0.9)
        self.repo.record_executions(
            session_id,
            [_per_agent()],
            aggregated,
            duration_ms=1500,
            capture=capture,
            model="model-x",
        )

        row = self._get_row(session_id)
        self.assertEqual(row.status, "completed")
        self.assertEqual(row.duration_ms, 1500)
        self.assertEqual(json.loads(row.dispatched_agents), ["security"])

        with Session(self._engine) as s:
            rows = s.exec(
                select(AgentExecution).where(
                    AgentExecution.review_session_id == session_id
                )
            ).all()
        by_agent = {r.agent_name: r for r in rows}
        self.assertEqual(set(by_agent), {"security", "aggregator"})
        self.assertEqual(by_agent["security"].duration_ms, 250)
        self.assertEqual(by_agent["security"].model, "model-a")
        self.assertAlmostEqual(by_agent["security"].confidence, 0.8)
        self.assertEqual(by_agent["aggregator"].duration_ms, 1500)
        self.assertEqual(by_agent["aggregator"].model, "model-root")
        parsed = json.loads(by_agent["aggregator"].result)
        self.assertEqual(parsed["agent_name"], "aggregator")

    def test_record_executions_falls_back_to_model_param(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model=None,
            expected_agents=["security"],
            user_id="alice",
        )
        capture = _FakeCapture(models={})  # no captured models → fall back
        self.repo.record_executions(
            session_id,
            [_per_agent()],
            _per_agent("aggregator"),
            duration_ms=10,
            capture=capture,
            model="fallback-model",
        )
        with Session(self._engine) as s:
            rows = s.exec(
                select(AgentExecution).where(
                    AgentExecution.review_session_id == session_id
                )
            ).all()
        by_agent = {r.agent_name: r for r in rows}
        self.assertEqual(by_agent["security"].model, "fallback-model")
        self.assertEqual(by_agent["aggregator"].model, "fallback-model")

    # --- get_aggregated_result / get_tool_calls ------------------------------

    def test_get_aggregated_result_returns_json_string_or_none(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model=None,
            expected_agents=[],
        )
        self.assertIsNone(self.repo.get_aggregated_result(session_id))
        with Session(self._engine) as s:
            s.add(
                AgentExecution(
                    review_session_id=session_id,
                    agent_name="aggregator",
                    duration_ms=100,
                    result=json.dumps({"agent_name": "aggregator"}),
                )
            )
            s.commit()
        raw = self.repo.get_aggregated_result(session_id)
        self.assertEqual(json.loads(raw)["agent_name"], "aggregator")

    def test_get_tool_calls_returns_metadata_dicts(self):
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="abc123",
            request_type="review",
            model=None,
            expected_agents=[],
        )
        with Session(self._engine) as s:
            s.add(
                ReviewToolCall(
                    review_session_id=session_id,
                    agent_name="compliance",
                    tool_name="jira_get_issue",
                    tool_latency_ms=500,
                    tool_status="success",
                )
            )
            s.commit()

        calls = self.repo.get_tool_calls(session_id)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["agent_name"], "compliance")
        self.assertEqual(calls[0]["tool_name"], "jira_get_issue")
        self.assertEqual(calls[0]["tool_latency_ms"], 500)
        self.assertEqual(calls[0]["tool_status"], "success")
        self.assertEqual(self.repo.get_tool_calls(999), [])


    # --- find_latest_by_conversation ----------------------------------------

    def test_find_latest_by_conversation_returns_most_recent(self):
        """Returns the most recent review (any status) for a conversation."""
        # Create two reviews for the same conversation — older running, newer completed
        older_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="aaa",
            request_type="review",
            model=None,
            expected_agents=[],
            conversation_id=10,
            user_id="alice",
        )
        self.repo.mark_completed(older_id, duration_ms=100, dispatched_agents=[])
        newer_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="bbb",
            request_type="compliance_question",
            model=None,
            expected_agents=[],
            conversation_id=10,
            user_id="alice",
        )
        row = self.repo.find_latest_by_conversation(10, "alice")
        self.assertIsNotNone(row)
        self.assertEqual(row.id, newer_id)

    def test_find_latest_by_conversation_enforces_user_id(self):
        """Returns None when user_id doesn't match."""
        self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="aaa",
            request_type="review",
            model=None,
            expected_agents=[],
            conversation_id=10,
            user_id="alice",
        )
        self.assertIsNone(self.repo.find_latest_by_conversation(10, "bob"))

    def test_find_latest_by_conversation_returns_none_for_empty(self):
        """Returns None when no reviews exist for the conversation."""
        self.assertIsNone(self.repo.find_latest_by_conversation(999, "alice"))

    def test_find_latest_by_conversation_includes_running(self):
        """Finds a running review (not just completed)."""
        session_id = self.repo.create(
            repo_id="org/repo",
            graph_commit_hash="aaa",
            request_type="review",
            model=None,
            expected_agents=[],
            conversation_id=10,
            user_id="alice",
        )
        row = self.repo.find_latest_by_conversation(10, "alice")
        self.assertIsNotNone(row)
        self.assertEqual(row.id, session_id)
        self.assertEqual(row.status, "running")


if __name__ == "__main__":
    unittest.main()
