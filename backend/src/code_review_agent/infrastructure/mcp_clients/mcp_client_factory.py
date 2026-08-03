"""Shared MultiServerMCPClient for the four review MCP servers.

Constructed ONCE in FastAPI's lifespan (stored on app.state.mcp_client) — never
per-request. Four HTTP connection setups per POST /review call would be real,
avoidable latency.

Safety notes (do not relax):
- ``crg`` uses settings.crg_server_url (Phase 1's setting) — docker-compose
  overrides it to http://crg-server:5555/mcp; a hardcoded 127.0.0.1 breaks the
  container deployment.
- ``github`` enforces read-only server-side via X-MCP-Readonly plus a scoped
  X-MCP-Toolsets header; client-side per-agent tool filtering is the second,
  deliberately redundant layer.
- ``tool_name_prefix`` stays at its default (False). Do not add prefix-stripping
  or fuzzy tool-name-matching to scoped(); CRG's own tool names already contain
  underscores as part of the real name, so naive stripping corrupts them.
- ``handle_tool_errors`` stays at its default (True): an MCP tool failure comes
  back as a ToolMessage(status="error") for the agent to handle instead of
  crashing the review.
"""

from langchain_mcp_adapters.client import MultiServerMCPClient

from infrastructure.config import settings


def build_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "crg": {
                "transport": "streamable_http",
                "url": settings.crg_server_url,
            },
            "github": {
                "transport": "streamable_http",
                "url": "https://api.githubcopilot.com/mcp/",
                "headers": {
                    "Authorization": f"Bearer {settings.github_pat}",
                    "X-MCP-Readonly": "true",
                    "X-MCP-Toolsets": "repos,issues,pull_requests,code_security,dependabot,actions",
                },
            },
            "atlassian": {
                "transport": "streamable_http",
                "url": settings.atlassian_mcp_url,
            },
            "context7": {
                "transport": "streamable_http",
                "url": "https://mcp.context7.com/mcp",
                "headers": (
                    {"CONTEXT7_API_KEY": settings.context7_api_key}
                    if settings.context7_api_key
                    else {}
                ),
            },
        }
    )


def scoped(tools: list, allowed_names: set[str]) -> list:
    """Return only the tools whose names are in allowed_names."""
    return [t for t in tools if t.name in allowed_names]
