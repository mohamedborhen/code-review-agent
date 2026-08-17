"""Unit tests for the POST /review recency touch helper (Branch-Aware §11).

Regression: `_touch_recency` wraps the eviction-LRU bookkeeping write so a
failure (e.g. SQLite locked past busy_timeout, I/O error) can never abort the
review flow before its audit rows are written. It must call the store with the
right args on the happy path and swallow exceptions otherwise.
"""

import unittest
from unittest import mock

from infrastructure.api.routes.review import _touch_recency


class _RecordingStore:
    def __init__(self, fail: bool = False):
        self.calls = []
        self.fail = fail

    def touch_requested_at(self, repo_id: str, branch: str) -> None:
        self.calls.append((repo_id, branch))
        if self.fail:
            raise RuntimeError("database is locked")


class TouchRecencyTest(unittest.TestCase):
    def test_calls_store_with_repo_and_branch(self):
        store = _RecordingStore()
        _touch_recency(store, "acme/app", "feature")
        self.assertEqual(store.calls, [("acme/app", "feature")])

    def test_swallows_store_failure(self):
        store = _RecordingStore(fail=True)
        with mock.patch("infrastructure.api.routes.review.logger") as logger:
            _touch_recency(store, "acme/app", "feature")  # must not raise
        logger.warning.assert_called_once()

    def test_missing_row_is_noop(self):
        store = _RecordingStore()
        _touch_recency(store, "acme/app", "missing")  # must not raise
        self.assertEqual(store.calls, [("acme/app", "missing")])


if __name__ == "__main__":
    unittest.main()