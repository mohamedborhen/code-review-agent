import shutil
import subprocess
from pathlib import Path

from domain.repo.repo_source_port import RepoSourcePort


def _run_git(args: list[str], cwd: str, pat: str | None = None) -> str:
    """Run a git command with optional PAT injection via http.extraHeader.

    PAT is injected via ``-c http.extraHeader=Authorization: Bearer <pat>``
    rather than embedded in the URL (which leaks into .git/config).
    """
    cmd = ["git"]
    if pat:
        cmd.extend(["-c", f"http.extraHeader=Authorization: Bearer {pat}"])
    cmd.extend(args)
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else str(result)
        raise RuntimeError(
            f"git command failed: git {' '.join(args)}\n{stderr}"
        )
    return result.stdout.strip()


def detect_branch(local_path: str) -> str:
    """Return the checked-out branch at ``local_path``, or the repo's default
    branch if HEAD is detached, or ``""`` if neither can be determined.

    ``git clone --depth 1`` checks out the repo's default branch, but a Phase 1
    webhook sync does ``git fetch origin <sha>; git checkout <sha>`` which
    detaches HEAD — so ``git branch --show-current`` alone is insufficient for
    the migration backfill. ``refs/remotes/origin/HEAD`` records the default
    branch the clone was created from, so it is the deterministic fallback.
    """
    try:
        current = _run_git(["branch", "--show-current"], cwd=local_path)
        if current:
            return current
    except RuntimeError:
        pass
    try:
        sym = _run_git(
            ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=local_path
        )
        if sym.startswith("origin/"):
            return sym[len("origin/"):]
        return sym
    except RuntimeError:
        return ""


class GitRepoSource(RepoSourcePort):
    def clone(self, repo_url: str, local_path: str, pat: str | None = None) -> str:
        target_path = Path(local_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists():
            shutil.rmtree(target_path)

        _run_git(
            ["clone", "--depth", "1", repo_url, str(target_path)],
            cwd=".",
            pat=pat,
        )
        output = _run_git(["rev-parse", "HEAD"], cwd=str(target_path))
        return output

    def sync(self, local_path: str, ref: str, pat: str | None = None) -> str:
        _run_git(["fetch", "origin", ref], cwd=local_path, pat=pat)
        _run_git(["checkout", ref], cwd=local_path)
        output = _run_git(["rev-parse", "HEAD"], cwd=local_path)
        return output

    def create_worktree(
        self, base_repo_path: str, branch: str, target_path: str, pat: str | None = None
    ) -> str:
        # A Phase 1 clone is shallow (`git clone --depth 1`), which implies a
        # single-branch clone: only the default branch's ref exists. Fetch the
        # requested branch into a local ref first, or `git worktree add` fails
        # with "no such ref".
        _run_git(
            ["fetch", "origin", f"{branch}:{branch}"],
            cwd=base_repo_path,
            pat=pat,
        )
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            ["worktree", "add", target_path, branch],
            cwd=base_repo_path,
        )
        output = _run_git(["rev-parse", "HEAD"], cwd=target_path)
        return output

    def update_worktree(
        self, worktree_path: str, branch: str, pat: str | None = None
    ) -> str:
        # The single-branch refspec (`--depth 1`) means `git fetch origin
        # <branch>` only updates FETCH_HEAD. Fetch into the remote-tracking ref
        # so `git reset --hard origin/<branch>` (spec §3) resolves. `fetch` alone
        # would not update the already-checked-out files; `reset --hard`
        # guarantees a clean tree even after a previous failed build left
        # stray files.
        _run_git(
            ["fetch", "origin", f"{branch}:refs/remotes/origin/{branch}"],
            cwd=worktree_path,
            pat=pat,
        )
        _run_git(["reset", "--hard", f"origin/{branch}"], cwd=worktree_path)
        output = _run_git(["rev-parse", "HEAD"], cwd=worktree_path)
        return output

    def current_branch(self, local_path: str) -> str:
        return detect_branch(local_path)
