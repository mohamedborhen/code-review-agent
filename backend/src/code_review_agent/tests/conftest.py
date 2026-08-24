"""Shared test fixtures for the test suite."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest
from sqlmodel import SQLModel, create_engine

import infrastructure.db.engine as engine_module
import infrastructure.db.models  # noqa: F401  (register tables on metadata)


@pytest.fixture(scope="session")
def tmp_engine():
    """Session-scoped temporary SQLite engine for tests."""
    tmp_dir = tempfile.mkdtemp(prefix="test_suite_")
    db_path = Path(tmp_dir) / "test_suite.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(test_engine)
    return test_engine
