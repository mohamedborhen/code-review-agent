import asyncio
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from domain.entities.graph_build_status import GraphBuildStatus
from domain.graph.graph_builder_port import GraphBuilderPort


class CRGToolError(Exception):
    def __init__(self, content: list) -> None:
        self.content = content
        super().__init__(str(content))


class CRGMcpAdapter(GraphBuilderPort):
    def __init__(self, server_url: str) -> None:
        self._server_url = server_url

    def build(self, repo_root: str) -> GraphBuildStatus:
        return _call_crg(self._server_url, "build_or_update_graph_tool", {
            "repo_root": repo_root,
            "full_rebuild": True,
        })

    def update(self, repo_root: str, base: str) -> GraphBuildStatus:
        return _call_crg(self._server_url, "build_or_update_graph_tool", {
            "repo_root": repo_root,
            "full_rebuild": False,
            "base": base,
        })


def _call_crg(
    server_url: str, tool_name: str, arguments: dict, max_retries: int = 3
) -> GraphBuildStatus:
    commit_hash = arguments.get("base", "unknown")

    for attempt in range(max_retries):
        try:
            return asyncio.run(_call_crg_async(server_url, tool_name, arguments))
        except (ConnectionRefusedError, TimeoutError, OSError) as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return GraphBuildStatus(
                commit_hash=commit_hash,
                status="error",
                error_message=f"Transport failure after {max_retries} retries: {e}",
            )
        except CRGToolError as e:
            return GraphBuildStatus(
                commit_hash=commit_hash,
                status="error",
                error_message=f"CRG tool error: {e}",
            )


async def _call_crg_async(
    server_url: str, tool_name: str, arguments: dict
) -> GraphBuildStatus:
    commit_hash = arguments.get("base", "unknown")

    async with streamable_http_client(server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)

            if result.isError:
                raise CRGToolError(result.content)

            return GraphBuildStatus(
                commit_hash=commit_hash,
                status="ready",
                completed_at=None,
            )
