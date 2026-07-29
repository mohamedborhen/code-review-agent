from typing import Protocol


class RepoSourcePort(Protocol):
    def clone(self, repo_url: str, local_path: str) -> str:
        ...

    def sync(self, local_path: str, ref: str) -> str:
        ...
