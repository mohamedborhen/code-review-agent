"""Unit tests for worktree-aware eviction (Branch-Aware addendum §11).

Covers the E.15 fix: ``_find_base_clone`` must resolve the base clone as a
sibling of the worktree (not walk up to the worktree's own ``.git`` file), so
worktree eviction reaches the ``git worktree remove`` path instead of falling
back to ``shutil.rmtree``. No DB, no live services — fake dirs in a temp sandbox.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from infrastructure.workspace.workspace_eviction_service import WorkspaceEvictionService


class WorkspaceEvictionServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.base = self.root / "acme_app"
        self.base.mkdir()
        (self.base / ".git").mkdir()
        self.worktree = self.root / "acme_app__feature"
        self.worktree.mkdir()
        (self.worktree / ".git").write_text(f"gitdir: {self.root / '.acme_app__feature.lock'}\n")
        self.service = WorkspaceEvictionService(str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_find_base_clone_resolves_sibling_base_for_worktree(self):
        base = self.service._find_base_clone("acme/app", self.worktree)
        self.assertEqual(base, self.base)

    def test_is_worktree_true_for_registered_worktree(self):
        with mock.patch(
            "infrastructure.workspace.workspace_eviction_service.subprocess.run",
            return_value=mock.Mock(stdout=f"worktree {self.worktree}\n"),
        ):
            self.assertTrue(self.service._is_worktree(self.base, self.worktree))

    def test_base_clone_itself_is_not_a_worktree(self):
        self.assertFalse(self.service._is_worktree(self.base, self.base))


if __name__ == "__main__":
    unittest.main()
