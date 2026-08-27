"""Regression tests for re-cloning over an existing workspace on Windows.

``git`` marks loose objects under ``.git/objects/`` read-only. A plain
``shutil.rmtree`` therefore raises ``PermissionError: [WinError 5]`` on Windows,
which made ``GitRepoSource.clone`` fail for *every* re-clone (re-registration of
a repo, or a re-clone after LRU workspace eviction that left the directory
behind). ``register_and_build`` swallows that exception and leaves ``local_path``
empty, so the ``RepoWorkspace`` row is never written and
``GET /api/v1/repos/{repo_id}/branches`` returns 404 forever.
"""

import os
import stat
from pathlib import Path
from unittest.mock import patch

from infrastructure.repo_source.git_repo_source import GitRepoSource, _force_rmtree


def _make_readonly_clone(root: Path) -> Path:
    """Simulate an existing shallow clone whose git objects are read-only."""
    target = root / "existing_repo"
    objects = target / ".git" / "objects" / "ab"
    objects.mkdir(parents=True)
    obj_file = objects / "cdef1234567890"
    obj_file.write_bytes(b"binary-object")
    os.chmod(obj_file, stat.S_IREAD)
    return target


class TestForceRmtree:
    def test_removes_tree_containing_readonly_file(self, tmp_path):
        target = _make_readonly_clone(tmp_path)
        assert target.exists()

        _force_rmtree(target)

        assert not target.exists()

    def test_missing_path_is_a_noop(self, tmp_path):
        _force_rmtree(tmp_path / "does-not-exist")

    def test_removes_plain_writable_tree(self, tmp_path):
        target = tmp_path / "plain"
        (target / "nested").mkdir(parents=True)
        (target / "nested" / "file.txt").write_text("hello", encoding="utf-8")

        _force_rmtree(target)

        assert not target.exists()


class TestCloneOverExistingWorkspace:
    def test_clone_replaces_workspace_with_readonly_git_objects(self, tmp_path):
        target = _make_readonly_clone(tmp_path)

        with patch("infrastructure.repo_source.git_repo_source._run_git") as run_git:
            run_git.return_value = "deadbeef"
            sha = GitRepoSource().clone("https://github.com/example/repo", str(target))

        assert sha == "deadbeef"
        assert run_git.call_count == 2

    def test_clone_into_fresh_path_still_works(self, tmp_path):
        target = tmp_path / "fresh"

        with patch("infrastructure.repo_source.git_repo_source._run_git") as run_git:
            run_git.return_value = "cafebabe"
            sha = GitRepoSource().clone("https://github.com/example/repo", str(target))

        assert sha == "cafebabe"
