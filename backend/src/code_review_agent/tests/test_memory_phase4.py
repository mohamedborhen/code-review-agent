"""Phase 4 tests: memory store, LangMem namespace isolation, summarization config,
and the tool_scoping truncation fix.

Uses a dedicated temp SQLite engine (mock.patch of the module-global engine
during init_db) matching tests/test_conversation_phase3.py — never the real
Phase 1/2 DB. The LangGraph memory store (AsyncSqliteStore) is exercised over
in-memory aiosqlite connections in the namespace tests and over a temp-file
connection for the build_memory_store path test.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import aiosqlite
import pytest

from langchain_core.tools import StructuredTool
from langgraph.store.sqlite import AsyncSqliteStore
from sqlmodel import Session, create_engine, text

import infrastructure.agents_runtime.memory_store as memory_store_module
import infrastructure.agents_runtime.orchestrator_runtime as orchestrator_module
import infrastructure.agents_runtime.tool_scoping as tool_scoping_module
import infrastructure.db.engine as engine_module
import infrastructure.db.models  # noqa: F401  (register tables on metadata)
from infrastructure.config import settings

_TMP = tempfile.mkdtemp(prefix="p4tests_")
_DB_PATH = Path(_TMP) / "p4tests.db"
_test_engine = create_engine(f"sqlite:///{_DB_PATH}")


@pytest.fixture(scope="module", autouse=True)
def _init():
    # init_db() + all its helpers reference the module-global `engine`; patching
    # it routes schema creation onto our temp DB (same pattern as Phase 3 tests).
    with mock.patch.object(engine_module, "engine", _test_engine):
        engine_module.init_db()


@pytest.fixture(autouse=True)
def _clean_between_tests():
    # The module-scoped DB persists across tests; wipe rows in FK-safe order.
    with Session(_test_engine) as session:
        for name in ("agentexecution", "ToolCall", "MemorySummary", "Message", "Conversation"):
            session.execute(text(f"DELETE FROM {name}"))
        session.commit()
    yield


async def _in_memory_store():
    """AsyncSqliteStore over an in-memory aiosqlite connection."""
    conn = await aiosqlite.connect(":memory:", isolation_level=None)
    store = AsyncSqliteStore(conn)  # no index config
    await store.setup()
    return store, conn


def _namespace_template_of(tool):
    """Pull the LangMem NamespaceTemplate out of a memory tool's closure.

    langmem binds the template as a closure cell; locating it by type (instead
    of a positional index) keeps the test robust across tool kinds.
    """
    from langmem.utils import NamespaceTemplate

    for cell in getattr(tool.coroutine, "__closure__", ()) or ():
        if isinstance(cell.cell_contents, NamespaceTemplate):
            return cell.cell_contents
    raise AssertionError(f"no NamespaceTemplate in {tool.name} closure")


# --------------------------------------------------------------------------- #
# 1. LangMem namespace isolation: shared vs private, user/repo scoping         #
# --------------------------------------------------------------------------- #


def test_memory_namespace_isolation() -> None:
    async def main() -> None:
        store, conn = await _in_memory_store()
        try:
            # Shared scope: per user AND per repo.
            await store.aput(("memories", "shared", "alice", "acme/repo"), "k1", {"content": "shared fact"})
            # Private scopes: per subagent literal.
            await store.aput(
                ("memories", "private", "alice", "acme/repo", "security"), "k1", {"content": "security secret"}
            )
            await store.aput(
                ("memories", "private", "alice", "acme/repo", "performance"), "k1", {"content": "performance secret"}
            )
            # Cross-tenant rows must stay invisible.
            await store.aput(("memories", "shared", "bob", "acme/repo"), "k1", {"content": "bob shared fact"})
            await store.aput(("memories", "shared", "alice", "other/repo"), "k1", {"content": "alice other repo fact"})

            # Security CANNOT read Performance's private memory.
            sec = await store.asearch(("memories", "private", "alice", "acme/repo", "security"))
            sec_values = [item.value["content"] for item in sec]
            assert sec_values == ["security secret"]
            assert "performance secret" not in sec_values

            # Performance cannot read Security's private memory either.
            perf = await store.asearch(("memories", "private", "alice", "acme/repo", "performance"))
            assert [item.value["content"] for item in perf] == ["performance secret"]

            # A different repo_id cannot read another repo's shared memory.
            shared_acme = await store.asearch(("memories", "shared", "alice", "acme/repo"))
            assert [item.value["content"] for item in shared_acme] == ["shared fact"]
            shared_other = await store.asearch(("memories", "shared", "alice", "other/repo"))
            assert [item.value["content"] for item in shared_other] == ["alice other repo fact"]

            # A different user_id cannot read another user's shared memory.
            bob = await store.asearch(("memories", "shared", "bob", "acme/repo"))
            assert [item.value["content"] for item in bob] == ["bob shared fact"]

            # Shared and private scopes do not bleed into each other.
            shared_all = await store.asearch(("memories", "shared", "alice", "acme/repo"))
            assert all(item.value["content"] != "security secret" for item in shared_all)
        finally:
            await conn.close()

    asyncio.run(main())


def test_memory_tools_resolve_phase4_namespaces() -> None:
    """The tool factories bake the exact Phase 4 namespaces in — shared with the
    {user_id}/{repo_id} placeholders, private with the literal agent name — and
    those placeholders resolve from config.configurable at runtime (the LangGraph
    mechanism, never an LLM tool arg; PHASE_4.md §6.2)."""
    from infrastructure.agents_runtime.memory_tools import (
        SHARED_MEMORY_NAMESPACE,
        build_private_memory_tools,
        build_shared_memory_tools,
    )

    assert SHARED_MEMORY_NAMESPACE == ("memories", "shared", "{user_id}", "{repo_id}")
    shared = build_shared_memory_tools()
    assert [t.name for t in shared] == ["manage_memory", "search_memory"]
    private = build_private_memory_tools("security")
    assert [t.name for t in private] == ["manage_memory", "search_memory"]

    config = {"configurable": {"user_id": "alice", "repo_id": "acme/repo"}}
    shared_manage, shared_search = (_namespace_template_of(t)(config) for t in shared)
    assert shared_manage == ("memories", "shared", "alice", "acme/repo")
    assert shared_search == ("memories", "shared", "alice", "acme/repo")

    private_manage, private_search = (_namespace_template_of(t)(config) for t in private)
    assert private_manage == ("memories", "private", "alice", "acme/repo", "security")
    assert private_search == ("memories", "private", "alice", "acme/repo", "security")


# --------------------------------------------------------------------------- #
# 2. Summarization constants + SummarizationMiddleware construction            #
# --------------------------------------------------------------------------- #


def test_summarization_trigger_constants() -> None:
    assert settings.summarization_trigger_tokens == 222822  # 85% of 262,144
    assert settings.summarization_keep_tokens == 26214  # 10% of 262,144

    from deepagents.backends.state import StateBackend
    from deepagents.middleware.summarization import SummarizationMiddleware

    # Construction only — no API call, no key needed for building the object.
    # deepagents 0.7 delegates the thresholds to langchain's inner helper.
    middleware = SummarizationMiddleware(
        model=settings.review_model,
        backend=StateBackend(),
        trigger=("tokens", settings.summarization_trigger_tokens),
        keep=("tokens", settings.summarization_keep_tokens),
    )
    assert middleware._lc_helper.trigger == (
        "tokens",
        settings.summarization_trigger_tokens,
    )
    assert middleware._lc_helper.keep == ("tokens", settings.summarization_keep_tokens)


# --------------------------------------------------------------------------- #
# 3. Exactly one summarization node (replace-by-name, no double-summarization) #
# --------------------------------------------------------------------------- #


def test_exactly_one_summarization_middleware() -> None:
    """deepagents auto-adds a SummarizationMiddleware; an explicit one REPLACES
    it by .name in place, never alongside it (PHASE_4.md §9 Q1).

    The middleware is a model-call wrapper composed into the `model` node
    closure, so it does not appear in the compiled graph's node list — the
    count is asserted on the assembled middleware stack, which is exactly what
    langchain's create_agent validates (it raises on duplicate names).
    """
    from deepagents.backends.state import StateBackend
    from deepagents.graph import _apply_custom_middleware, create_summarization_middleware
    from deepagents.middleware.summarization import SummarizationMiddleware
    from langchain.chat_models import init_chat_model

    backend = StateBackend()
    model = init_chat_model(settings.review_model)  # construction only, no API call

    # deepagents' own auto-built entry (what create_deep_agent appends).
    base = [create_summarization_middleware(model, backend)]
    assert len([m for m in base if m.name == "SummarizationMiddleware"]) == 1

    explicit = SummarizationMiddleware(
        model=settings.review_model,
        backend=backend,
        trigger=("tokens", settings.summarization_trigger_tokens),
        keep=("tokens", settings.summarization_keep_tokens),
    )
    merged = _apply_custom_middleware(base, [explicit])
    summ = [m for m in merged if m.name == "SummarizationMiddleware"]
    assert len(summ) == 1, "explicit middleware must REPLACE the auto one, not join it"
    assert summ[0] is explicit  # in-place replacement keeps the stack order

    # With NO explicit middleware the auto entry is the only one (still exactly 1).
    untouched = _apply_custom_middleware(base, [])
    assert len([m for m in untouched if m.name == "SummarizationMiddleware"]) == 1


def test_deep_agent_compiles_with_explicit_summarization_middleware() -> None:
    """The full create_deep_agent graph still compiles with the Phase 4
    middleware + shared StateBackend (construction only — no ainvoke)."""
    from deepagents import create_deep_agent
    from deepagents.backends.state import StateBackend
    from deepagents.middleware.summarization import SummarizationMiddleware

    backend = StateBackend()
    agent = create_deep_agent(
        model=settings.review_model,
        backend=backend,
        middleware=[
            SummarizationMiddleware(
                model=settings.review_model,
                backend=backend,
                trigger=("tokens", settings.summarization_trigger_tokens),
                keep=("tokens", settings.summarization_keep_tokens),
            )
        ],
    )
    nodes = agent.get_graph().nodes
    assert "model" in nodes and "tools" in nodes
    # langchain's create_agent raises on duplicate middleware names — compiling
    # proves exactly one SummarizationMiddleware survived the merge.


# --------------------------------------------------------------------------- #
# 4. Store path reuse: build_memory_store targets settings.metadata_db_path    #
# --------------------------------------------------------------------------- #


def test_build_memory_store_uses_metadata_db_path_without_index() -> None:
    db_file = Path(_TMP) / "memory_store_test.db"
    with mock.patch.object(memory_store_module.settings, "metadata_db_path", str(db_file)):

        async def main() -> None:
            store = await memory_store_module.build_memory_store()
            try:
                # No index/embeddings config (PHASE_4.md §6.4).
                assert store.index_config is None
                # The connection actually opened settings.metadata_db_path.
                cur = await store.conn.execute(
                    "SELECT file FROM pragma_database_list WHERE name = 'main'"
                )
                row = await cur.fetchone()
                assert os.path.normcase(os.path.abspath(row[0])) == os.path.normcase(
                    os.path.abspath(str(db_file))
                )
                # setup() is idempotent and created the store tables.
                cur2 = await store.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('store','store_migrations')"
                )
                tables = {r[0] for r in await cur2.fetchall()}
                assert {"store", "store_migrations"} <= tables
            finally:
                await store.conn.close()

        asyncio.run(main())


# --------------------------------------------------------------------------- #
# 5. tool_scoping truncation fix (PHASE-4 TOP PRIORITY)                        #
# --------------------------------------------------------------------------- #


def test_event_wrapper_returns_full_result_but_truncates_event_log() -> None:
    """A >4000-char tool result must reach the CALLER untruncated (the audit
    path json.loads it) while the event-log copy stays capped at 2000 chars."""

    big = "x" * 5000
    calls = []

    async def _big_tool() -> str:
        return big

    async def _fake_log_event(*args, **kwargs):  # noqa: ANN002, ANN003
        calls.append((args, kwargs))

    tool = StructuredTool.from_function(
        coroutine=_big_tool, name="big_recall", description="returns a huge payload"
    )
    wrapped = tool_scoping_module._wrap_with_events(tool, "test_agent")
    assert wrapped is not tool  # actually wrapped

    async def main() -> None:
        with mock.patch.object(
            tool_scoping_module, "log_event", new=mock.AsyncMock(side_effect=_fake_log_event)
        ):
            result = await wrapped.ainvoke({})

        # Caller-facing result is FULLY untruncated (audit path can json.loads it).
        assert result == big
        assert len(result) == 5000

        # Event-log copy is truncated: content capped at 2000 chars + suffix.
        tool_result_entries = [
            kwargs["output"] for args, kwargs in calls if args and args[0] == "tool_result"
        ]
        assert tool_result_entries, "expected a tool_result event entry"
        logged = tool_result_entries[-1]
        assert logged == "x" * 2000 + "...(truncated)"

    asyncio.run(main())


def test_audited_context_tool_parses_large_recall_as_ok() -> None:
    """Regression for PHASE_4.md §0.1: a large-but-successful recall (JSON >
    4000 chars, realistic at limit≈25) must be audited as status='ok' with the
    real results_count — not invalid_response/0."""
    results = [
        {"message_id": i, "role": "user", "snippet": "long snippet " + "y" * 200, "score": 0.5}
        for i in range(1, 26)
    ]
    payload = json.dumps({"conversation_id": 7, "results": results})
    assert len(payload) > 4000, "test fixture must exceed the old truncation cap"

    async def _big_search(**kwargs):
        return payload

    tool = StructuredTool.from_function(
        coroutine=_big_search, name="search_messages", description="read-only search"
    )

    class _FakeMCPClient:
        async def get_tools(self, server_name: str) -> list:
            return [tool]

    recorded: dict = {}

    class _RecordingAudit:
        def record_context_invocation(
            self, conversation_id, query, results_count, latency_ms, status, review_session_id=None
        ):
            recorded.update(
                {"conversation_id": conversation_id, "count": results_count, "status": status}
            )

    from infrastructure.agents_runtime.subagents.context_agent_runtime import get_audited_context_tool

    async def main() -> None:
        audit = _RecordingAudit()
        audited = await get_audited_context_tool(
            _FakeMCPClient(),
            conversation_id=7,
            user_id="alice",
            repo_id="acme/repo",
            audit=audit,
            review_session_id=42,
            store=None,
        )
        raw = await audited.ainvoke({"query": "CLIP-4", "limit": 25})
        parsed = json.loads(raw)
        assert parsed.get("error") is None
        assert len(parsed["results"]) == 25
        assert recorded["status"] == "ok", f"large recall misreported: {recorded}"
        assert recorded["count"] == 25
        assert recorded["conversation_id"] == 7

    asyncio.run(main())


# --------------------------------------------------------------------------- #
# 6. Durable summary wiring (PHASE_4.md §5.3)                                  #
# --------------------------------------------------------------------------- #


def _temp_engine_repo():
    """SQLModelConversationRepository bound to the test temp engine."""
    from infrastructure.db.conversation_repository import SQLModelConversationRepository

    return SQLModelConversationRepository(_test_engine)


def test_durable_summary_persists_memory_summary_row() -> None:
    """_write_durable_conversation_summary persists a MemorySummary row via the
    ConversationStorePort with the injected LLM summarizer's text."""
    from domain.entities.agent_finding import AgentInput
    from infrastructure.db.models import Conversation, Message, MemorySummary

    with Session(_test_engine) as session:
        conv = Conversation(repo_id="acme/repo", user_id="alice")
        session.add(conv)
        session.commit()
        session.refresh(conv)
        conversation_id = conv.id
        session.add(
            Message(
                conversation_id=conversation_id,
                role="user",
                event_type="final",
                content="what about CLIP-4?",
                order_index=1,
            )
        )
        session.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                event_type="final",
                content="CLIP-4 mitigation approved",
                order_index=2,
            )
        )
        session.commit()

    review_input = AgentInput(
        repo_id="acme/repo",
        graph_commit_hash="abc123",
        request_type="any_question",
        conversation_id=conversation_id,
        user_id="alice",
    )

    async def main() -> None:
        with mock.patch.object(
            orchestrator_module,
            "SQLModelConversationRepository",
            new=lambda: _temp_engine_repo(),
        ), mock.patch.object(
            orchestrator_module, "_build_llm_summarizer"
        ) as fake_builder:
            async def _stub_summarizer(recent_messages):
                assert len(recent_messages) == 2
                return "LLM summary of the session"

            fake_builder.return_value = _stub_summarizer
            await orchestrator_module._write_durable_conversation_summary(review_input)

    asyncio.run(main())

    with Session(_test_engine) as session:
        rows = session.exec(
            MemorySummary.__table__.select().where(MemorySummary.conversation_id == conversation_id)
        ).all()
        assert rows, "expected a MemorySummary row for the review run"
        row = rows[-1]
        assert row.summary_text == "LLM summary of the session"
        assert row.summarized_up_to_message_id is not None


def test_durable_summary_helper_raises_on_db_error() -> None:
    """A DB error inside the durable-summary path propagates from the helper —
    run_review wraps the call in try/except so a summary failure NEVER fails the
    review (PHASE_4.md §5.3). This test pins the helper's contract at the
    boundary the wrapper protects."""
    from domain.entities.agent_finding import AgentInput

    review_input = AgentInput(
        repo_id="acme/repo",
        graph_commit_hash="abc123",
        request_type="any_question",
        conversation_id=1,
        user_id="alice",
    )

    async def main() -> None:
        with mock.patch.object(
            orchestrator_module, "SQLModelConversationRepository"
        ) as fake_cls:
            fake_repo = mock.MagicMock()
            fake_repo.list_messages.side_effect = RuntimeError("db is locked")
            fake_cls.return_value = fake_repo
            with pytest.raises(RuntimeError):
                await orchestrator_module._write_durable_conversation_summary(review_input)

    asyncio.run(main())
