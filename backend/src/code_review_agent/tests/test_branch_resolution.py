"""Unit tests for the branch → commit resolver (Branch-Aware addendum §4).

Regression (#4): a non-JSON GitHub tool payload (e.g. an MCP tool error /
rate-limit message) must raise BranchNotFoundError for the caller to respond
404 — not bubble up as an uncaught ValueError → 500.
"""

import asyncio
import unittest

from infrastructure.mcp_clients.branch_resolution import (
    BranchNotFoundError,
    list_repo_branches,
    resolve_branch_to_commit,
)


class _FakeTool:
    def __init__(self, name: str, result: object) -> None:
        self.name = name
        self._result = result

    async def ainvoke(self, inputs: object, **kwargs) -> object:
        return self._result


class _FakeClient:
    def __init__(self, tool: _FakeTool) -> None:
        self._tool = tool

    async def get_tools(self, server_name: str) -> list:
        return [self._tool]


class BranchResolutionTest(unittest.TestCase):
    def _run(self, tool_result) -> object:
        async def go():
            client = _FakeClient(_FakeTool("list_branches", tool_result))
            return await list_repo_branches(client, "acme", "app")

        return asyncio.run(go())

    def test_valid_json_list_returns_branches(self):
        result = self._run([{"type": "text", "text": '[{"name": "main", "sha": "abc"}]'}])
        self.assertEqual(result, [{"name": "main", "sha": "abc"}])

    def test_non_json_payload_raises_branch_not_found(self):
        with self.assertRaises(BranchNotFoundError):
            self._run([{"type": "text", "text": "rate limit exceeded"}])

    def test_empty_text_returns_empty_list(self):
        self.assertEqual(self._run([{"type": "text", "text": ""}]), [])

    def test_resolve_branch_to_commit_matches_by_name(self):
        async def go():
            client = _FakeClient(
                _FakeTool("list_branches", [{"type": "text", "text": '[{"name": "bug/1", "sha": "def456"}]'}])
            )
            return await resolve_branch_to_commit(client, "acme", "app", "bug/1")

        self.assertEqual(asyncio.run(go()), "def456")


if __name__ == "__main__":
    unittest.main()