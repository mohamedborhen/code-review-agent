"""Unit tests for the per-branch workspace repository (Branch-Aware §7/§11).

Regression: `touch_requested_at` must update `last_requested_at` when a
workspace row is accessed — the route calls it on the POST /review success path
so the eviction LRU orders branches by most-recent access, not first build.
Uses a temp SQLite engine (no live DB, no services).
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from sqlmodel import SQLModel, Session, create_engine, select

import infrastructure.db.models  # noqa: F401  (register tables on metadata)
import infrastructure.db.repo_workspace_repository as repo_module
from infrastructure.db.models import RepoWorkspace


class SQLModelRepoWorkspaceRepositoryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "test.db"
        self._engine = create_engine(f"sqlite:///{db_path}")
        SQLModel.metadata.create_all(self._engine)

    def tearDown(self):
        self._engine.dispose()
        self._tmp.cleanup()

    def test_touch_requested_at_updates_recency(self):
        repo = repo_module.SQLModelRepoWorkspaceRepository()
        with mock.patch.object(repo_module, "engine", self._engine):
            with Session(self._engine) as session:
                session.add(
                    RepoWorkspace(
                        repo_id="acme/app",
                        branch="feature",
                        local_path="/ws/acme_app__feature",
                        last_synced_commit="abc123",
                        last_requested_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    )
                )
                session.commit()

            repo.touch_requested_at("acme/app", "feature")

            with Session(self._engine) as session:
                row = session.exec(
                    select(RepoWorkspace).where(
                        RepoWorkspace.repo_id == "acme/app",
                        RepoWorkspace.branch == "feature",
                    )
                ).first()
        self.assertIsNotNone(row)
        # SQLite round-trips DATETIME as naive wall time (PHASE_2.md), so compare
        # against a naive reference rather than the aware value written above.
        self.assertGreater(row.last_requested_at, datetime(2020, 1, 1))

    def test_touch_requested_at_missing_row_is_noop(self):
        repo = repo_module.SQLModelRepoWorkspaceRepository()
        with mock.patch.object(repo_module, "engine", self._engine):
            repo.touch_requested_at("acme/app", "missing")  # must not raise


if __name__ == "__main__":
    unittest.main()