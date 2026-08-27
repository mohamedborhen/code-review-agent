"""Regression test for FIX 12: ExceptionGroup from MCP tools must not crash reviews.

When handle_tool_error=True, tool errors (including ExceptionGroup from GitHub
MCP search_code) must be returned as error strings, not re-raised. This
prevents the entire review from failing due to a single flaky MCP tool call.
"""
import asyncio
import pytest
from unittest.mock import MagicMock
from langchain_core.tools import StructuredTool


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.record_call = MagicMock()
    return store


def _make_tool(name: str, handle_tool_error: bool = True):
    """Create a StructuredTool that raises ExceptionGroup on invocation."""

    async def _raising(**kwargs):
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [ConnectionError("GitHub MCP transport broken")],
        )

    return StructuredTool.from_function(
        coroutine=_raising,
        name=name,
        description=f"Test tool {name}",
        handle_tool_error=handle_tool_error,
    )


def test_handle_tool_error_returns_string_on_exception_group(mock_store):
    """ExceptionGroup must be returned as error string when handle_tool_error=True."""
    from infrastructure.agents_runtime.tool_scoping import _wrap_with_events

    tool = _make_tool("search_code", handle_tool_error=True)
    wrapped = _wrap_with_events(tool, "compliance", store=mock_store)

    async def go():
        return await wrapped.ainvoke({"query": "test"})

    result = asyncio.run(go())

    assert isinstance(result, str)
    assert "ERROR" in result
    assert "ExceptionGroup" in result
    assert "TaskGroup" in result


def test_handle_tool_error_false_still_raises(mock_store):
    """When handle_tool_error=False, the exception must still be re-raised."""
    from infrastructure.agents_runtime.tool_scoping import _wrap_with_events

    tool = _make_tool("search_code", handle_tool_error=False)
    wrapped = _wrap_with_events(tool, "compliance", store=mock_store)

    async def go():
        return await wrapped.ainvoke({"query": "test"})

    with pytest.raises(ExceptionGroup, match="TaskGroup"):
        asyncio.run(go())


def test_successful_tool_passes_through(mock_store):
    """Successful tool calls must not be affected by the fix."""
    from infrastructure.agents_runtime.tool_scoping import _wrap_with_events

    async def _ok(**kwargs):
        return "success result"

    tool = StructuredTool.from_function(
        coroutine=_ok,
        name="get_file_contents",
        description="test",
        handle_tool_error=True,
    )
    wrapped = _wrap_with_events(tool, "compliance", store=mock_store)

    async def go():
        return await wrapped.ainvoke({"path": "/foo"})

    result = asyncio.run(go())
    assert result == "success result"


def test_regular_exception_also_handled(mock_store):
    """Non-ExceptionGroup errors must also be returned as strings."""
    from infrastructure.agents_runtime.tool_scoping import _wrap_with_events

    async def _raising(**kwargs):
        raise ConnectionError("server unavailable")

    tool = StructuredTool.from_function(
        coroutine=_raising,
        name="list_commits",
        description="test",
        handle_tool_error=True,
    )
    wrapped = _wrap_with_events(tool, "compliance", store=mock_store)

    async def go():
        return await wrapped.ainvoke({"repo": "test"})

    result = asyncio.run(go())

    assert isinstance(result, str)
    assert "ERROR" in result
    assert "ConnectionError" in result
