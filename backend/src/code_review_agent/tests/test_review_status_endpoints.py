"""Tests for Issue 1: Review status endpoints — GET /reviews/running and GET /reviews/{session_id}.

Tests verify helper functions with user_id enforcement and route registration.
"""

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from infrastructure.api.routes.review import (
    _find_running_review,
    _get_review_session,
    _get_aggregated_result,
    _get_tool_calls,
)
from infrastructure.db.engine import engine
from infrastructure.db.models import AgentExecution, ReviewSession, ReviewToolCall


class ReviewStatusEndpointsTest(unittest.TestCase):
    def setUp(self):
        """Create a fresh in-memory SQLite DB for each test."""
        self.test_engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.test_engine)
        # Patch the module-level engine used by the helpers
        self._engine_patcher = patch("infrastructure.api.routes.review.engine", self.test_engine)
        self._engine_patcher.start()

    def tearDown(self):
        self._engine_patcher.stop()

    def _create_session(self, **kwargs) -> int:
        defaults = {
            "repo_id": "org/repo",
            "graph_commit_hash": "abc123",
            "request_type": "review",
            "status": "running",
            "user_id": "alice",
            "conversation_id": 1,
        }
        defaults.update(kwargs)
        with Session(self.test_engine) as s:
            row = ReviewSession(**defaults)
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def test_get_review_session_returns_when_user_matches(self):
        """_get_review_session returns session when user_id matches."""
        session_id = self._create_session(user_id="alice")
        result = _get_review_session(session_id, "alice")
        self.assertIsNotNone(result)
        self.assertEqual(result.id, session_id)
        self.assertEqual(result.user_id, "alice")

    def test_get_review_session_returns_none_on_mismatch(self):
        """_get_review_session returns None when user_id doesn't match."""
        session_id = self._create_session(user_id="alice")
        result = _get_review_session(session_id, "bob")
        self.assertIsNone(result)

    def test_get_review_session_returns_none_for_nonexistent(self):
        """_get_review_session returns None for nonexistent session."""
        result = _get_review_session(999, "alice")
        self.assertIsNone(result)

    def test_find_running_review_returns_when_matches(self):
        """_find_running_review returns session when conversation_id + user_id match."""
        session_id = self._create_session(conversation_id=13, user_id="alice", status="running")
        result = _find_running_review(13, "alice")
        self.assertIsNotNone(result)
        self.assertEqual(result.id, session_id)

    def test_find_running_review_returns_none_on_user_mismatch(self):
        """_find_running_review returns None when user_id doesn't match."""
        self._create_session(conversation_id=13, user_id="alice", status="running")
        result = _find_running_review(13, "bob")
        self.assertIsNone(result)

    def test_find_running_review_returns_none_on_conversation_mismatch(self):
        """_find_running_review returns None when conversation_id doesn't match."""
        self._create_session(conversation_id=13, user_id="alice", status="running")
        result = _find_running_review(99, "alice")
        self.assertIsNone(result)

    def test_find_running_review_returns_none_when_not_running(self):
        """_find_running_review returns None when session is not running."""
        self._create_session(conversation_id=13, user_id="alice", status="completed")
        result = _find_running_review(13, "alice")
        self.assertIsNone(result)

    def test_get_aggregated_result_returns_json_string(self):
        """_get_aggregated_result returns the result JSON string."""
        session_id = self._create_session()
        with Session(self.test_engine) as s:
            s.add(AgentExecution(
                review_session_id=session_id,
                agent_name="aggregator",
                duration_ms=1000,
                result=json.dumps({"agent_name": "aggregator", "findings": []}),
            ))
            s.commit()
        raw = _get_aggregated_result(session_id)
        self.assertIsNotNone(raw)
        parsed = json.loads(raw)
        self.assertEqual(parsed["agent_name"], "aggregator")

    def test_get_aggregated_result_returns_none_when_missing(self):
        """_get_aggregated_result returns None when no aggregator row."""
        session_id = self._create_session()
        raw = _get_aggregated_result(session_id)
        self.assertIsNone(raw)

    def test_get_tool_calls_returns_metadata(self):
        """_get_tool_calls returns list of tool call metadata dicts."""
        session_id = self._create_session()
        with Session(self.test_engine) as s:
            s.add(ReviewToolCall(
                review_session_id=session_id,
                agent_name="compliance",
                tool_name="jira_get_issue",
                tool_latency_ms=500,
                tool_status="success",
            ))
            s.add(ReviewToolCall(
                review_session_id=session_id,
                agent_name="security",
                tool_name="code_scanning_alerts",
                tool_latency_ms=300,
                tool_status="error",
            ))
            s.commit()
        calls = _get_tool_calls(session_id)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["agent_name"], "compliance")
        self.assertEqual(calls[0]["tool_name"], "jira_get_issue")
        self.assertEqual(calls[0]["tool_status"], "success")
        self.assertEqual(calls[1]["tool_status"], "error")

    def test_get_tool_calls_returns_empty_when_no_rows(self):
        """_get_tool_calls returns empty list when no tool calls."""
        session_id = self._create_session()
        calls = _get_tool_calls(session_id)
        self.assertEqual(calls, [])


class RouteRegistrationTest(unittest.TestCase):
    def test_reviews_running_route_exists(self):
        """GET /reviews/running route is registered."""
        from infrastructure.api.routes.review import router
        routes = {r.path: r.methods for r in router.routes}
        self.assertIn("/reviews/running", routes)
        self.assertIn("GET", routes["/reviews/running"])

    def test_reviews_by_id_route_exists(self):
        """GET /reviews/{session_id} route is registered."""
        from infrastructure.api.routes.review import router
        routes = {r.path: r.methods for r in router.routes}
        self.assertIn("/reviews/{session_id}", routes)
        self.assertIn("GET", routes["/reviews/{session_id}"])

    def test_reviews_running_declared_before_by_id(self):
        """FastAPI first-match-wins: /reviews/running must be before /reviews/{session_id}."""
        from infrastructure.api.routes.review import router
        route_paths = [r.path for r in router.routes if hasattr(r, "path")]
        running_idx = route_paths.index("/reviews/running")
        by_id_idx = route_paths.index("/reviews/{session_id}")
        self.assertLess(running_idx, by_id_idx)
