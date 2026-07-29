from typing import Protocol

from domain.entities.graph_build_status import GraphBuildStatus


class GraphStatusQueryPort(Protocol):
    def get_status(self, repo_id: str, commit_hash: str) -> GraphBuildStatus | None:
        ...


class GraphReadinessService:
    def __init__(self, query_port: GraphStatusQueryPort) -> None:
        self._query_port = query_port

    def is_ready(self, repo_id: str, commit_hash: str) -> bool:
        status = self._query_port.get_status(repo_id, commit_hash)
        if status is None:
            return False
        return status.status == "ready"
