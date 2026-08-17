"""Phase 3 tests: conversation schema, FTS5 search_messages, migration, turn flow.

Uses a dedicated temp SQLite engine (mock.patch of the module-global engine
during init_db), matching tests/test_repo_workspace_repository.py — never the
real Phase 1/2 DB and never dependent on import order / env-var timing.
"""

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from sqlmodel import SQLModel, Session, create_engine, text

import infrastructure.db.engine as engine_module
import infrastructure.db.models  # noqa: F401  (register tables on metadata)
import infrastructure.mcp_clients.servers.conversation_server as server_module
from infrastructure.db.conversation_ports_adapters import SQLModelConversationAudit
from infrastructure.db.conversation_repository import SQLModelConversationRepository
from infrastructure.db.models import AgentExecution, Conversation, Message, ToolCall

_TMP = tempfile.mkdtemp(prefix="p3tests_")
_DB_PATH = Path(_TMP) / "p3tests.db"
_test_engine = create_engine(f"sqlite:///{_DB_PATH}")


@pytest.fixture(scope="module", autouse=True)
def _init():
    # init_db() + all its helpers reference the module-global `engine`; patching
    # it routes schema creation (incl. message_fts + triggers) onto our temp DB.
    with mock.patch.object(engine_module, "engine", _test_engine):
        engine_module.init_db()


@pytest.fixture(autouse=True)
def _clean_between_tests():
    # The module-scoped DB persists across tests; wipe rows in FK-safe order
    # (agentexecution references Conversation, so it must go first) so
    # UNIQUE(conversation_id, order_index) never collides.
    with Session(_test_engine) as session:
        for name in ("agentexecution", "ToolCall", "MemorySummary", "Message", "Conversation"):
            session.execute(text(f"DELETE FROM {name}"))
        session.commit()
    yield


def _seed(conversations: list[tuple[str, str]], messages: list[tuple[int, str, str, str, int]]) -> None:
    with Session(_test_engine) as session:
        for repo_id, user_id in conversations:
            session.add(Conversation(repo_id=repo_id, user_id=user_id))
        session.commit()
        for conv_id, role, event_type, content, order in messages:
            session.add(
                Message(
                    conversation_id=conv_id,
                    role=role,
                    event_type=event_type,
                    content=content,
                    order_index=order,
                )
            )
        session.commit()


def _raw() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_init_creates_pascal_case_tables_and_fts() -> None:
    conn = _raw()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"Conversation", "Message", "ToolCall", "MemorySummary"} <= tables
    assert "message_fts" in tables
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"message_ai", "message_ad", "message_au"} <= triggers
    conn.close()


def test_agentexecution_nullable_review_session_and_conversation_id() -> None:
    conn = _raw()
    cols = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(agentexecution)")}
    assert cols["review_session_id"] == 0  # notnull=0 -> nullable (spec §2.3)
    assert cols["conversation_id"] == 0  # optional conversation FK
    conn.close()


def test_fts_phrase_quoting_hyphen() -> None:
    _seed([("acme/repo", "alice")], [(1, "user", "final", "The CLIP-4 fix needs a review", 0)])
    conn = _raw()
    row = conn.execute(
        "SELECT count(*) FROM message_fts WHERE message_fts MATCH ?", ('"CLIP-4"',)
    ).fetchone()
    assert row[0] == 1
    conn.close()


def test_search_messages_authorization_cross_tenant() -> None:
    _seed(
        [("acme/repo", "alice"), ("acme/repo", "mallory")],
        [
            (1, "user", "final", "alice private token", 0),
            (1, "assistant", "final", "alice's CLIP-4 reply", 1),
            (2, "user", "final", "mallory secret", 0),
        ],
    )

    async def main() -> None:
        with mock.patch.object(server_module, "_DB_PATH", _DB_PATH):
            alice = json.loads(await server_module.search_messages(1, "alice", "acme/repo", "CLIP-4"))
            assert alice.get("error") is None and len(alice["results"]) == 1, alice
            mallory = json.loads(await server_module.search_messages(1, "mallory", "acme/repo", "CLIP-4"))
            assert mallory["error"] == "not_found" and mallory["results"] == []
            # cross-tenant: alice cannot read conversation 2 (she doesn't own it)
            cross = json.loads(await server_module.search_messages(2, "alice", "acme/repo", "secret"))
            assert cross["error"] == "not_found"
            # unknown conversation behaves identically (no IDOR leak)
            ghost = json.loads(await server_module.search_messages(999, "alice", "acme/repo", "token"))
            assert ghost["error"] == "not_found"

    asyncio.run(main())


def test_turn_persists_messages_and_audit() -> None:
    from application.conversation_service.run_conversation_turn import run_conversation_turn

    repo = SQLModelConversationRepository(_test_engine)
    _seed([("acme/repo", "alice")], [])
    audit = SQLModelConversationAudit(_test_engine)

    class _NullAgent:
        async def search_context(self, conversation_id, user_id, repo_id, query, limit=10):
            from domain.entities.conversation_entity import ContextRetrieval

            return ContextRetrieval(conversation_id=conversation_id)

    async def main() -> None:
        outcome = await run_conversation_turn(
            1,
            "alice",
            "acme/repo",
            "hello",
            store=repo,
            context_agent=_NullAgent(),
            audit=audit,
        )
        assert outcome["conversation_id"] == 1
        assert outcome["assistant_reply"]
        messages = repo.list_messages(1)
        assert [m.role for m in messages] == ["user", "assistant"]
        assert [m.order_index for m in messages] == [1, 2]  # monotonic
        with Session(_test_engine) as session:
            rows = session.exec(
                AgentExecution.__table__.select().where(AgentExecution.agent_name == "context_agent")
            ).all()
            assert rows, "context_agent audit row missing"
            payload = json.loads(rows[-1].result)
            assert payload["conversation_id"] == 1
            assert "snippet" not in payload  # audit privacy: no content/snippets

    asyncio.run(main())


def test_unique_order_index_enforced() -> None:
    _seed([("acme/repo", "alice")], [(1, "user", "final", "first", 1)])
    conn = _raw()
    try:
        conn.execute(
            "INSERT INTO Message (conversation_id, role, event_type, content, order_index) "
            "VALUES (1,'user','final','duplicate',1)"
        )
        conn.commit()
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    finally:
        conn.close()
    assert raised, "UNIQUE(conversation_id, order_index) not enforced"


def test_foreign_keys_active_cascade() -> None:
    _seed([("acme/repo", "alice")], [(1, "user", "final", "doomed", 1)])
    conn = _raw()
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("DELETE FROM Conversation WHERE id=1")
    conn.commit()
    row = conn.execute("SELECT count(*) FROM Message WHERE conversation_id=1").fetchone()
    assert row[0] == 0, "ON DELETE CASCADE did not fire (FK not active)"
    conn.close()
