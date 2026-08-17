from sqlalchemy import event
from sqlmodel import SQLModel, create_engine

from infrastructure.config import settings

engine = create_engine(f"sqlite:///{settings.metadata_db_path}")


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()


def init_db() -> None:
    import infrastructure.db.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _add_model_columns()
    _rebuild_repoworkspace()


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
    backfilled from the existing ``updated_at``. Guarded: a fresh DB already has
    the new shape (created by ``create_all`` above), so the rebuild is skipped
    when the ``branch`` column is present.
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
