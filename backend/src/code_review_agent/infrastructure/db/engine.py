from sqlalchemy import event
from sqlmodel import SQLModel, create_engine

import logging
import os

from infrastructure.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(f"sqlite:///{settings.metadata_db_path}")


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    # Enforce FK constraints on every connection (Phase 3 DoD §10: "FK
    # constraints active"). SQLite ships with foreign_keys OFF by default, so
    # ON DELETE CASCADE on Message/ToolCall/MemorySummary never fires without
    # this — orphan rows would be possible. Phase 1/2 tables have no FKs that
    # this pragma could break.
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


def init_db() -> None:
    import infrastructure.db.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _add_model_columns()
    _rebuild_repoworkspace()
    _rebuild_agentexecution()
    _create_fts_index()


def _add_model_columns() -> None:
    """Additive, guarded column migration for existing Phase 2 tables.

    ``create_all`` only creates missing tables — it never adds columns to
    existing ones — so the new ``model`` columns are ALTERed in idempotently.
    Documented schema-evolution exception to the AGENTS.md "no new startup
    wiring in db/engine.py" rule: that rule concerns new tables, the migration
    is additive, and it introduces no new dependency (see OPENCODE.md).
    """
    with engine.begin() as conn:
        column_defs = [
            ("reviewsession", "model", "TEXT"),
            ("agentexecution", "model", "TEXT"),
            # session lifecycle / audit (see db/models.py ReviewSession)
            ("reviewsession", "status", "TEXT"),
            ("reviewsession", "error", "TEXT"),
            ("reviewsession", "duration_ms", "INTEGER"),
            ("reviewsession", "completed_at", "DATETIME"),
            ("reviewsession", "expected_agents", "TEXT"),
            ("reviewsession", "dispatched_agents", "TEXT"),
            # review status endpoints (Issue 1)
            ("reviewsession", "conversation_id", "INTEGER"),
            ("reviewsession", "user_id", "TEXT"),
            # tool result persistence (Issue 2 — ReviewToolCall input/output)
            ("reviewtoolcall", "tool_input", "TEXT"),
            ("reviewtoolcall", "tool_output", "TEXT"),
        ]
        for table, column, sql_type in column_defs:
            cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
                )


def _rebuild_repoworkspace() -> None:
    """4-step SQLite table rebuild: ``repoworkspace`` becomes per-branch.

    ``create_all`` only creates missing tables and ``_add_model_columns`` only
    adds columns — neither can change ``repo_id UNIQUE`` into the composite
    ``UNIQUE(repo_id, branch)`` the Branch-Aware addendum requires (§7). SQLite
    supports no constraint changes via ALTER TABLE, so the standard 4-step
    rebuild (create/insert/drop/rename) runs inside one transaction.

    Branch is backfilled deterministically from each row's real clone via
    ``detect_branch`` (never guessed/hardcoded), and ``last_requested_at`` is
    backfilled from the existing ``updated_at``. A row whose ``local_path``
    directory no longer exists is a stale/orphaned entry — it is skipped and
    logged so it cannot brick startup; a live clone whose branch cannot be
    determined still raises. Guarded: a fresh DB already has the new shape
    (created by ``create_all`` above), so the rebuild is skipped when the
    ``branch`` column is present.
    """
    from infrastructure.repo_source.git_repo_source import detect_branch

    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(repoworkspace)")}
        if "branch" in cols:
            return

        rows = conn.exec_driver_sql(
            "SELECT id, repo_id, local_path, last_synced_commit, created_at, updated_at "
            "FROM repoworkspace"
        ).fetchall()

        conn.exec_driver_sql(
            """
            CREATE TABLE repoworkspace_new (
                id INTEGER NOT NULL,
                repo_id VARCHAR NOT NULL,
                branch VARCHAR NOT NULL,
                local_path VARCHAR NOT NULL,
                last_synced_commit VARCHAR,
                last_requested_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                UNIQUE (repo_id, branch)
            )
            """
        )

        for row_id, repo_id, local_path, last_synced, created_at, updated_at in rows:
            branch = detect_branch(local_path)
            if not branch:
                # Refuse to guess a branch (spec §7). A row whose local_path
                # no longer exists is a stale/orphaned entry (e.g. its worktree
                # was removed out-of-band) — skip and log it so a single stale
                # row cannot brick application startup. A live clone whose
                # branch genuinely cannot be determined still fails loudly.
                if not os.path.isdir(local_path):
                    logger.warning(
                        "repoworkspace migration: skipping stale row repo=%r "
                        "local_path=%r (directory no longer exists)",
                        repo_id,
                        local_path,
                    )
                    continue
                raise RuntimeError(
                    f"repoworkspace migration: cannot determine branch at {local_path!r} "
                    f"for repo {repo_id!r}; refusing to guess"
                )
            conn.exec_driver_sql(
                "INSERT INTO repoworkspace_new "
                "(id, repo_id, branch, local_path, last_synced_commit, "
                "last_requested_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    repo_id,
                    branch,
                    local_path,
                    last_synced,
                    updated_at,
                    created_at,
                    updated_at,
                ),
            )

        conn.exec_driver_sql("DROP TABLE repoworkspace")
        conn.exec_driver_sql("ALTER TABLE repoworkspace_new RENAME TO repoworkspace")
        conn.exec_driver_sql("CREATE INDEX ix_repoworkspace_repo_id ON repoworkspace (repo_id)")


def _rebuild_agentexecution() -> None:
    """4-step SQLite table rebuild: ``AgentExecution`` gets a nullable
    ``review_session_id`` and an optional ``conversation_id`` FK.

    ``create_all`` only creates missing tables and ``_add_model_columns`` only
    adds columns — neither can relax ``review_session_id NOT NULL`` or add the
    ``conversation_id`` FK. SQLite supports no constraint changes via ALTER
    TABLE, so the standard 4-step rebuild (create/insert/drop/rename) runs
    inside one transaction, following the established ``_rebuild_repoworkspace``
    pattern (PHASE_3.md §2.3).

    Every existing column is carried over so no audit data is lost. A fresh DB
    already has the new shape (created by ``create_all`` above), so the rebuild
    is skipped when ``conversation_id`` is present.
    """
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(agentexecution)")}
        if "conversation_id" in cols:
            return

        rows = conn.exec_driver_sql(
            "SELECT id, review_session_id, agent_name, duration_ms, confidence, "
            "model, result, created_at FROM agentexecution"
        ).fetchall()

        conn.exec_driver_sql(
            """
            CREATE TABLE agentexecution_temp (
                id INTEGER NOT NULL,
                review_session_id INTEGER NULL REFERENCES ReviewSession(id),
                conversation_id INTEGER NULL REFERENCES Conversation(id),
                agent_name VARCHAR NOT NULL,
                duration_ms INTEGER NOT NULL,
                confidence FLOAT,
                model VARCHAR,
                result VARCHAR NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id)
            )
            """
        )

        for row in rows:
            conn.exec_driver_sql(
                "INSERT INTO agentexecution_temp "
                "(id, review_session_id, conversation_id, agent_name, duration_ms, "
                "confidence, model, result, created_at) "
                "VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)",
                tuple(row),
            )

        conn.exec_driver_sql("DROP TABLE agentexecution")
        conn.exec_driver_sql("ALTER TABLE agentexecution_temp RENAME TO agentexecution")


def _create_fts_index() -> None:
    """FTS5 virtual table + sync triggers for Message.content.

    Documented startup-wiring exception (PHASE_3.md §1, AGENTS.md): raw DDL runs
    inside ``init_db()`` because ``message_fts`` is a virtual table SQLModel's
    ``create_all`` cannot express. ``porter unicode61 tokenchars '_-.'`` keeps
    identifiers like ``CLIP-4`` / ``snake_case_file`` unshredded.
    """
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
                content,
                content='Message',
                content_rowid='id',
                tokenize = "porter unicode61 tokenchars '_-.'"
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS message_ai AFTER INSERT ON Message BEGIN
                INSERT INTO message_fts(rowid, content) VALUES (new.id, new.content);
            END
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS message_ad AFTER DELETE ON Message BEGIN
                INSERT INTO message_fts(message_fts, rowid, content) VALUES('delete', old.id, old.content);
            END
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS message_au AFTER UPDATE ON Message BEGIN
                INSERT INTO message_fts(message_fts, rowid, content) VALUES('delete', old.id, old.content);
                INSERT INTO message_fts(rowid, content) VALUES (new.id, new.content);
            END
            """
        )
