import shutil
import subprocess
from pathlib import Path

from domain.repo.repo_source_port import RepoSourcePort


def _run_git(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else str(result)
        raise RuntimeError(
            f"git command failed: git {' '.join(args)}\n{stderr}"
        )
    return result.stdout.strip()


class GitRepoSource(RepoSourcePort):
    def clone(self, repo_url: str, local_path: str) -> str:
        target_path = Path(local_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists():
            shutil.rmtree(target_path)

        _run_git(["clone", "--depth", "1", repo_url, str(target_path)], cwd=".")
        output = _run_git(["rev-parse", "HEAD"], cwd=str(target_path))
        return output

    def sync(self, local_path: str, ref: str) -> str:
        _run_git(["fetch", "origin", ref], cwd=local_path)
        _run_git(["checkout", ref], cwd=local_path)
        output = _run_git(["rev-parse", "HEAD"], cwd=local_path)
        return output
