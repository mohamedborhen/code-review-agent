import base64
from unittest.mock import patch

from infrastructure.repo_source.git_repo_source import _run_git


def test_git_pat_uses_basic_authorization_header():
    with patch("infrastructure.repo_source.git_repo_source.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""

        _run_git(["ls-remote", "https://github.com/example/repo"], ".", pat="pat-value")

    expected = base64.b64encode(b"x-access-token:pat-value").decode("ascii")
    command = run.call_args.args[0]
    assert f"http.extraHeader=Authorization: Basic {expected}" in command
