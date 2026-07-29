import re

from domain.entities.graph_build_status import GraphBuildStatus
from domain.entities.repo_workspace import RepoWorkspace
from domain.graph.graph_builder_port import GraphBuilderPort
from domain.repo.repo_source_port import RepoSourcePort


def _sanitize_repo_id(repo_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", repo_id)
    return safe.strip("_").lower() or "repo"


class CloneRepositoryService:
    def __init__(
        self,
        repo_source: RepoSourcePort,
        graph_builder: GraphBuilderPort,
    ) -> None:
        self._repo_source = repo_source
        self._graph_builder = graph_builder

    def execute(
        self,
        repo_url: str,
        repo_id: str,
        workspace_root: str,
    ) -> tuple[RepoWorkspace, GraphBuildStatus]:
        safe_id = _sanitize_repo_id(repo_id)
        local_path = f"{workspace_root.rstrip('/')}/{safe_id}"

        commit_sha = self._repo_source.clone(repo_url, local_path)

        workspace = RepoWorkspace(
            repo_id=repo_id,
            local_path=local_path,
            last_synced_commit=commit_sha,
        )

        build_status = self._graph_builder.build(repo_root=local_path)

        return workspace, build_status
