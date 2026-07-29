from domain.entities.graph_build_status import GraphBuildStatus
from domain.graph.graph_builder_port import GraphBuilderPort
from domain.repo.repo_source_port import RepoSourcePort


class SyncOnWebhookService:
    def __init__(
        self,
        repo_source: RepoSourcePort,
        graph_builder: GraphBuilderPort,
    ) -> None:
        self._repo_source = repo_source
        self._graph_builder = graph_builder

    def execute(
        self,
        local_path: str,
        commit_sha: str,
        last_indexed_commit: str | None,
    ) -> GraphBuildStatus:
        self._repo_source.sync(local_path, commit_sha)

        base = last_indexed_commit if last_indexed_commit else "HEAD~1"
        build_status = self._graph_builder.update(repo_root=local_path, base=base)

        return build_status
