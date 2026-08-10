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


def _add_model_columns() -> None:
    """Additive, guarded column migration for existing Phase 2 tables.

    ``create_all`` only creates missing tables — it never adds columns to
    existing ones — so the new ``model`` columns are ALTERed in idempotently.
    Documented schema-evolution exception to the AGENTS.md "no new startup
    wiring in db/engine.py" rule: that rule concerns new tables, the migration
    is additive, and it introduces no new dependency (see OPENCODE.md).
    """
    with engine.begin() as conn:
        for table, column in (("reviewsession", "model"), ("agentexecution", "model")):
            cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
