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
