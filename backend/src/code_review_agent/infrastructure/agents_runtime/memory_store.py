"""Single LangGraph BaseStore instance for agent long-term memory (Phase 4).

Exactly ONE ``AsyncSqliteStore`` is constructed in the whole process, inside the
async FastAPI lifespan (``main.py``) — the constructor captures the running
event loop, so it cannot be built at module import (PHASE_4.md §6.3). The
connection is opened manually so the standing SQLite PRAGMAs are applied:
neither store sets them by default, and every new connection touching shared
state must use WAL + busy_timeout + foreign_keys (AGENTS.md standing rule).

No ``index`` config: this project has rejected embedding/vector search twice
(PHASE_1's graph-over-embeddings hypothesis, PHASE_3 §6.1), so ``asearch`` is
exact-namespace only (PHASE_4.md §6.4). ``await store.setup()`` is idempotent
and creates only the ``store`` + ``store_migrations`` tables — no collision with
the Phase 1–3 tables (verified against langgraph-checkpoint-sqlite 3.1.1).

The langmem memory tools execute their async variants (``aput``/``asearch``)
inside deepagents' async graph, so the store MUST be the async variant — the
sync ``SqliteStore`` raises ``NotImplementedError`` on async operations.
"""

import logging

import aiosqlite
from langgraph.store.sqlite import AsyncSqliteStore

from infrastructure.config import settings

logger = logging.getLogger(__name__)


async def build_memory_store() -> AsyncSqliteStore:
    """Open the async SQLite connection, apply the PRAGMAs, build + setup the store.

    Call exactly once per process, from the async lifespan (a second
    ``AsyncSqliteStore`` over the same file would duplicate the WAL/checkpoint
    machinery; PHASE_4.md §2 forbids constructing a second store anywhere).
    """
    conn = await aiosqlite.connect(settings.metadata_db_path, isolation_level=None)
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=ON")
    # No index config — no embeddings (PHASE_4.md §6.4).
    store = AsyncSqliteStore(conn)
    await store.setup()  # idempotent; safe to await once at startup
    logger.info("AsyncSqliteStore built on %s", settings.metadata_db_path)
    return store
