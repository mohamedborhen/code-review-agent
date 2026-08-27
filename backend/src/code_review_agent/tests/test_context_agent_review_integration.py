"""Review Orchestrator <-> Context Agent integration tests (Phase 3 decisions).

Covers the build contract without a live LLM (updated for Phase 4: the root is
never tool-less — shared-memory tools are always granted; the Context Agent's
search_messages is ADDITIONAL, granted only with a conversation_id):
  1. no conversation_id -> root gets shared memory tools only (no search_messages)
  2. conversation_id without user_id -> 400
  3. server rejects identity (unknown conversation / not yours) -> not_found, no leak, review proceeds
  4. scope_agent_tools("context_agent") -> exactly ["search_messages"]
  5. orchestrator user message carries the conversation context block WITHOUT identity values
  6. no recall path: no audit row, no tool reachable
  7. recall path: audit row carries review_session_id + conversation_id, no snippets
  8. evidence provenance: prompt instructs message_id retention
  9. turn flow passes exclude_message_id
  10. exclude_message_id=None default keeps behavior (server-level, phase3 tests)
  11. limit/query bounds still enforced with new param
  12. recency-wins instruction present in prompt
  13. invalid_query/not_found handled gracefully, review continues
  14. hostile identity keys in ainvoke are REJECTED at schema validation (extra="forbid")
  15. LLM-visible args_schema exposes ONLY query/limit/exclude_message_id
  16. E2E: seeded fact -> review cites it (live, run separately)
  17. full suite green (pytest)
  18. get_tools raising (server down) -> context tool withheld, memory tools remain
  19. context_available=False omits the AVAILABLE prompt block (tool withheld)

Unit-testable subset runs here; live E2E is exercised via the running servers.
"""

import asyncio
import json
import unittest

from langchain_core.tools import StructuredTool

from domain.entities.agent_finding import AgentInput
from infrastructure.agents_runtime.capture import CaptureStore
from infrastructure.agents_runtime.orchestrator_runtime import (
    _build_root_tools,
    _build_user_message,
)
from infrastructure.agents_runtime.subagents.context_agent_runtime import (
    get_audited_context_tool,
)
from infrastructure.agents_runtime.tool_lists import AGENT_TOOL_PLAN

_SEARCH_RESULT = {
    "conversation_id": 7,
    "results": [
        {
            "message_id": 4,
            "role": "user",
            "snippet": "the CLIP-4 fix must be reviewed",
            "created_at": "2026-08-01T10:00:00Z",
            "score": 1.0,
        }
    ],
}


async def _fake_search(
    conversation_id: int,
    user_id: str,
    repo_id: str,
    query: str,
    limit: int = 10,
    exclude_message_id: int | None = None,
) -> str:
    if user_id != "alice" or repo_id != "acme/repo" or conversation_id != 7:
        return json.dumps({"conversation_id": conversation_id, "results": [], "error": "not_found"})
    return json.dumps(_SEARCH_RESULT)


def _fake_search_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=_fake_search,
        name="search_messages",
        description="Search the conversation's message history (read-only).",
    )


class _FakeMCPClient:
    def __init__(self, tools_by_server: dict) -> None:
        self._tools = tools_by_server

    async def get_tools(self, server_name: str) -> list:
        return self._tools.get(server_name, [])


class _UnavailableMCPClient:
    """Mimics MultiServerMCPClient.get_tools raising (down / not registered)."""

    async def get_tools(self, server_name: str) -> list:
        raise ValueError(f"Couldn't find a server with name '{server_name}'")


class _RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def record_context_invocation(
        self,
        conversation_id: int,
        query: str,
        results_count: int,
        latency_ms: int,
        status: str,
        review_session_id: int | None = None,
    ) -> None:
        self.calls.append(
            (conversation_id, query, results_count, latency_ms, status, review_session_id)
        )


def _agent_input(**overrides) -> AgentInput:
    base = dict(
        repo_id="acme/repo",
        graph_commit_hash="abc123",
        request_type="review",
        repo_root="/ws/acme_repo",
    )
    base.update(overrides)
    return AgentInput(**base)


class BuildRootToolsTest(unittest.IsolatedAsyncioTestCase):
    def test_no_conversation_id_grants_memory_tools_only(self):
        # Phase 4: the root is NEVER tool-less — the shared memory tool pair is
        # always granted. Without a conversation_id the Context Agent's
        # search_messages is withheld (Phase 2's "no tools" path is superseded
        # by the always-on shared-memory tools; see PHASE_4.md §6.2).
        client = _FakeMCPClient({"conversation": [_fake_search_tool()]})
        tools = asyncio.run(
            _build_root_tools(_agent_input(), client, None, CaptureStore())
        )
        self.assertEqual([t.name for t in tools], ["manage_memory", "search_memory"])

    def test_conversation_id_grants_memory_plus_search_messages(self):
        # Case 4: shared memory tools + exactly one context tool, search_messages.
        client = _FakeMCPClient({"conversation": [_fake_search_tool()]})
        tools = asyncio.run(
            _build_root_tools(
                _agent_input(conversation_id=7, user_id="alice"), client, 42, CaptureStore()
            )
        )
        self.assertEqual(
            [t.name for t in tools], ["manage_memory", "search_memory", "search_messages"]
        )

    def test_tool_unavailable_keeps_memory_tools(self):
        # Server down / not registered -> context tool withheld, shared memory
        # tools remain (root never tool-less), review proceeds.
        client = _FakeMCPClient({})
        tools = asyncio.run(
            _build_root_tools(
                _agent_input(conversation_id=7, user_id="alice"), client, 42, CaptureStore()
            )
        )
        self.assertEqual([t.name for t in tools], ["manage_memory", "search_memory"])

    def test_tool_server_down_keeps_memory_tools(self):
        # get_tools raises (real failure mode) -> context tool withheld, no crash.
        client = _UnavailableMCPClient()
        tools = asyncio.run(
            _build_root_tools(
                _agent_input(conversation_id=7, user_id="alice"), client, 42, CaptureStore()
            )
        )
        self.assertEqual([t.name for t in tools], ["manage_memory", "search_memory"])

    def test_explain_question_omits_search_messages(self):
        # explain_question (empty agent_names) must not grant search_messages.
        client = _FakeMCPClient({"conversation": [_fake_search_tool()]})
        tools = asyncio.run(
            _build_root_tools(
                _agent_input(conversation_id=7, user_id="alice"),
                client, 42, CaptureStore(), agent_names=[],
            )
        )
        self.assertEqual([t.name for t in tools], ["manage_memory", "search_memory"])

    def test_review_preserves_search_messages(self):
        # review (non-empty agent_names) must still grant search_messages.
        client = _FakeMCPClient({"conversation": [_fake_search_tool()]})
        tools = asyncio.run(
            _build_root_tools(
                _agent_input(conversation_id=7, user_id="alice"),
                client, 42, CaptureStore(), agent_names=["security"],
            )
        )
        self.assertIn("search_messages", [t.name for t in tools])

    def test_plan_entry_exactly_search_messages(self):
        self.assertEqual(
            AGENT_TOOL_PLAN["context_agent"], {"conversation": {"search_messages"}}
        )


class BuildUserMessageTest(unittest.TestCase):
    def test_no_conversation_omits_block(self):
        text = _build_user_message(_agent_input(), ["security"])
        self.assertNotIn("Historical conversation context is AVAILABLE", text)
        self.assertNotIn("conversation_id", text)

    def test_conversation_block_present_with_identity(self):
        text = _build_user_message(
            _agent_input(conversation_id=7, user_id="alice"), ["security"]
        )
        self.assertIn("Historical conversation context is AVAILABLE", text)
        # Case 5+12: evidence-only + recency-wins instructions.
        self.assertIn("evidence", text.lower())
        self.assertIn("most recent", text.lower())
        self.assertIn("BEFORE delegating", text)
        # Identity is closure-bound into the tool (§9.5) — the prompt no longer
        # declares the values the LLM should echo back.
        self.assertNotIn("conversation_id: 7", text)
        self.assertNotIn("user_id: alice", text)
        self.assertNotIn("repo_id: acme/repo", text)
        self.assertIn("pre-scoped", text)
        self.assertIn("do not pass conversation_id", text)

    def test_context_available_false_omits_block(self):
        # Degraded path (F2): conversation_id present but the tool was not
        # granted (server down) -> the AVAILABLE block must be omitted, so the
        # model is never told it has a tool it does not.
        text = _build_user_message(
            _agent_input(conversation_id=7, user_id="alice"),
            ["security"],
            context_available=False,
        )
        self.assertNotIn("Historical conversation context is AVAILABLE", text)
        self.assertNotIn("search_messages", text)
        self.assertNotIn("pre-scoped", text)


class AuditedContextToolTest(unittest.IsolatedAsyncioTestCase):
    async def _build(self, audit, client=None, **identity):
        client = client or _FakeMCPClient({"conversation": [_fake_search_tool()]})
        return await get_audited_context_tool(
            client,
            conversation_id=identity.get("conversation_id", 7),
            user_id=identity.get("user_id", "alice"),
            repo_id=identity.get("repo_id", "acme/repo"),
            audit=audit,
            review_session_id=identity.get("review_session_id", 42),
            store=CaptureStore(),
        )

    async def test_audit_row_carries_session_and_conversation(self):
        # Case 7: recall inside a review records review_session_id + conversation_id.
        audit = _RecordingAudit()
        tool = await self._build(audit)
        # Identity is bound at construction; the LLM supplies only the query.
        raw = await tool.ainvoke({"query": "CLIP-4", "limit": 10})
        self.assertEqual(json.loads(raw)["results"][0]["message_id"], 4)
        conv_id, query, count, _, status, session = audit.calls[0]
        self.assertEqual(conv_id, 7)
        self.assertEqual(query, "CLIP-4")
        self.assertEqual(count, 1)
        self.assertEqual(status, "ok")
        self.assertEqual(session, 42)

    async def test_not_found_audited_and_review_continues(self):
        # Case 3+13: server rejects (unknown conversation / not yours) -> not_found,
        # no leak, graceful. Identity is bound to a conversation the server rejects,
        # so the fake returns not_found and the review continues.
        audit = _RecordingAudit()
        tool = await self._build(audit, conversation_id=999, user_id="mallory", repo_id="acme/repo")
        raw = await tool.ainvoke({"query": "secret", "limit": 10})
        payload = json.loads(raw)
        self.assertEqual(payload["error"], "not_found")
        self.assertEqual(payload["results"], [])
        self.assertEqual(audit.calls[0][0], 999)
        self.assertEqual(audit.calls[0][4], "not_found")
        self.assertEqual(audit.calls[0][5], 42)

    async def test_invalid_query_audited_gracefully(self):
        # Case 11+13: query bounds / syntax errors surface as invalid_query.
        async def _invalid_search(**kwargs):
            return json.dumps({"conversation_id": 7, "results": [], "error": "invalid_query"})

        tool = StructuredTool.from_function(
            coroutine=_invalid_search, name="search_messages", description="read-only search"
        )
        audit = _RecordingAudit()
        client = _FakeMCPClient({"conversation": [tool]})
        wrapped = await self._build(audit, client=client)
        raw = await wrapped.ainvoke({"query": "x" * 250, "limit": 10})
        payload = json.loads(raw)
        self.assertEqual(payload["error"], "invalid_query")
        self.assertEqual(audit.calls[0][4], "invalid_query")

    async def test_wrapper_passes_exclude_message_id(self):
        # Case 9: turn flow forwards exclude_message_id through the wrapper path.
        seen: dict = {}

        async def _capturing_search(
            conversation_id: int,
            user_id: str,
            repo_id: str,
            query: str,
            limit: int = 10,
            exclude_message_id: int | None = None,
        ):
            seen.update(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "repo_id": repo_id,
                    "query": query,
                    "limit": limit,
                    "exclude_message_id": exclude_message_id,
                }
            )
            return json.dumps({"conversation_id": 7, "results": []})

        tool = StructuredTool.from_function(
            coroutine=_capturing_search, name="search_messages", description="read-only search"
        )
        audit = _RecordingAudit()
        client = _FakeMCPClient({"conversation": [tool]})
        wrapped = await self._build(audit, client=client, review_session_id=None)
        await wrapped.ainvoke({"query": "CLIP-4", "limit": 10, "exclude_message_id": 6})
        self.assertEqual(seen.get("exclude_message_id"), 6)
        # Identity is closure-injected server-side, not supplied by the caller.
        self.assertEqual(seen.get("conversation_id"), 7)
        self.assertEqual(seen.get("user_id"), "alice")
        self.assertEqual(seen.get("repo_id"), "acme/repo")

    async def test_hostile_identity_kwargs_rejected_at_validation(self):
        # Security boundary: a call that tries to smuggle identity keys is
        # REJECTED at schema validation (extra="forbid"), never overridden.
        from pydantic import ValidationError

        audit = _RecordingAudit()
        tool = await self._build(audit)
        with self.assertRaises(ValidationError):
            await tool.ainvoke(
                {
                    "query": "CLIP-4",
                    "conversation_id": 999,
                    "user_id": "mallory",
                    "repo_id": "evil/repo",
                }
            )
        # Rejected before the underlying tool ran: no audit row, no leak.
        self.assertEqual(audit.calls, [])

    async def test_llm_visible_schema_exposes_no_identity(self):
        # The LLM sees only query/limit/exclude_message_id — identity fields are
        # absent from the schema and additionalProperties is forbidden.
        audit = _RecordingAudit()
        tool = await self._build(audit)
        schema = tool.args_schema.model_json_schema()
        props = schema.get("properties", {})
        self.assertEqual(sorted(props.keys()), ["exclude_message_id", "limit", "query"])
        self.assertIs(schema.get("additionalProperties"), False)
        self.assertNotIn("conversation_id", props)
        self.assertNotIn("user_id", props)
        self.assertNotIn("repo_id", props)


class RouteValidationTest(unittest.TestCase):
    def test_conversation_id_without_user_id_raises(self):
        from fastapi import HTTPException

        from infrastructure.api.models import ReviewRequest
        from infrastructure.api.routes.review import _validate_conversation_identity

        body = ReviewRequest(
            repo_id="acme/repo", graph_commit_hash="abc123", request_type="review", conversation_id=7
        )
        with self.assertRaises(HTTPException) as ctx:
            _validate_conversation_identity(body)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_conversation_id_with_user_id_ok(self):
        from infrastructure.api.models import ReviewRequest
        from infrastructure.api.routes.review import _validate_conversation_identity

        body = ReviewRequest(
            repo_id="acme/repo",
            graph_commit_hash="abc123",
            request_type="review",
            conversation_id=7,
            user_id="alice",
        )
        _validate_conversation_identity(body)  # no exception

    def test_no_conversation_id_ok_without_user_id(self):
        from infrastructure.api.models import ReviewRequest
        from infrastructure.api.routes.review import _validate_conversation_identity

        body = ReviewRequest(repo_id="acme/repo", graph_commit_hash="abc123", request_type="review")
        _validate_conversation_identity(body)  # no exception


if __name__ == "__main__":
    unittest.main()