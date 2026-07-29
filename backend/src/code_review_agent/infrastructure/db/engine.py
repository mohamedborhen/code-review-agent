from sqlmodel import SQLModel, create_engine

from infrastructure.config import settings

engine = create_engine(f"sqlite:///{settings.metadata_db_path}")


def init_db() -> None:
    import infrastructure.db.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
