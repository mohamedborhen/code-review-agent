"""Tests for Issue 5: ReviewToolCall persistence — metadata-only, best-effort.

Verifies that _wrap_with_events persists ReviewToolCall rows on both
success and error paths, and that DB failures are swallowed.
"""

import unittest
from unittest.mock import MagicMock

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from infrastructure.agents_runtime.capture import CaptureStore
from infrastructure.agents_runtime.tool_scoping import _wrap_with_events
from infrastructure.db.models import ReviewToolCall


class DummyInput(BaseModel):
    query: str


async def _dummy_coroutine(query: str = "test") -> str:
    return "ok"


async def _failing_coroutine(query: str = "test") -> str:
    raise ValueError("tool failure")


DummyTool = StructuredTool.from_function(
    coroutine=_dummy_coroutine,
    name="dummy_tool",
    description="A dummy tool for testing",
    args_schema=DummyInput,
)

FailingTool = StructuredTool.from_function(
    coroutine=_failing_coroutine,
    name="failing_tool",
    description="A tool that always fails",
    args_schema=DummyInput,
)


class ReviewToolCallPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_path_persists_row(self):
        """Success path inserts ReviewToolCall with tool_status='success'."""
        mock_repo = MagicMock()
        store = CaptureStore()
        wrapped = _wrap_with_events(DummyTool, "compliance", store, review_session_id=42, tool_call_repo=mock_repo)

        result = await wrapped.ainvoke({"query": "test"})

        self.assertEqual(result, "ok")
        mock_repo.add.assert_called_once()
        call_arg = mock_repo.add.call_args[0][0]
        self.assertIsInstance(call_arg, ReviewToolCall)
        self.assertEqual(call_arg.review_session_id, 42)
        self.assertEqual(call_arg.agent_name, "compliance")
        self.assertEqual(call_arg.tool_name, "dummy_tool")
        self.assertEqual(call_arg.tool_status, "success")
        self.assertIsNotNone(call_arg.tool_latency_ms)
        self.assertGreaterEqual(call_arg.tool_latency_ms, 0)

    async def test_error_path_persists_row(self):
        """Error path inserts ReviewToolCall with tool_status='error'."""
        mock_repo = MagicMock()
        store = CaptureStore()
        wrapped = _wrap_with_events(FailingTool, "security", store, review_session_id=99, tool_call_repo=mock_repo)

        with self.assertRaises(ValueError):
            await wrapped.ainvoke({"query": "test"})

        mock_repo.add.assert_called_once()
        call_arg = mock_repo.add.call_args[0][0]
        self.assertIsInstance(call_arg, ReviewToolCall)
        self.assertEqual(call_arg.review_session_id, 99)
        self.assertEqual(call_arg.agent_name, "security")
        self.assertEqual(call_arg.tool_name, "failing_tool")
        self.assertEqual(call_arg.tool_status, "error")
        self.assertIsNotNone(call_arg.tool_latency_ms)

    async def test_skips_persist_when_no_session_id(self):
        """No ReviewToolCall row when review_session_id is None."""
        mock_repo = MagicMock()
        store = CaptureStore()
        wrapped = _wrap_with_events(DummyTool, "compliance", store, review_session_id=None, tool_call_repo=mock_repo)

        await wrapped.ainvoke({"query": "test"})

        mock_repo.add.assert_not_called()

    async def test_skips_persist_when_no_repo(self):
        """No ReviewToolCall row when tool_call_repo is None."""
        store = CaptureStore()
        wrapped = _wrap_with_events(DummyTool, "compliance", store, review_session_id=42, tool_call_repo=None)

        await wrapped.ainvoke({"query": "test"})

    async def test_db_failure_swallowed(self):
        """DB failure in repo.add is swallowed — tool call proceeds normally."""
        mock_repo = MagicMock()
        mock_repo.add.side_effect = RuntimeError("DB connection lost")
        store = CaptureStore()
        wrapped = _wrap_with_events(DummyTool, "compliance", store, review_session_id=42, tool_call_repo=mock_repo)

        result = await wrapped.ainvoke({"query": "test"})

        self.assertEqual(result, "ok")

    async def test_langmem_tools_not_wrapped(self):
        """Non-StructuredTool objects pass through unchanged."""
        # Create a plain object that is NOT a StructuredTool
        class PlainTool:
            name = "plain_tool"
            description = "Not a StructuredTool"

        plain = PlainTool()
        wrapped = _wrap_with_events(plain, "compliance", None, review_session_id=42, tool_call_repo=MagicMock())
        # Non-StructuredTool tools are returned as-is
        self.assertIs(wrapped, plain)
