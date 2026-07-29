from typing import Protocol

from domain.entities.graph_build_status import GraphBuildStatus


class GraphBuilderPort(Protocol):
    def build(self, repo_root: str) -> GraphBuildStatus:
        ...

    def update(self, repo_root: str, base: str) -> GraphBuildStatus:
        ...
