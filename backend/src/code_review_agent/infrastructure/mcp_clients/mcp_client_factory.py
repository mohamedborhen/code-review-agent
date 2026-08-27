"""Shared MultiServerMCPClient for the five review MCP servers.

Constructed ONCE in FastAPI's lifespan (stored on app.state.mcp_client) — never
per-request. Five HTTP connection setups per POST /review call would be real,
avoidable latency.

Safety notes (do not relax):
- ``crg`` uses settings.crg_server_url (Phase 1's setting) — docker-compose
  overrides it to http://crg-server:5555/mcp; a hardcoded 127.0.0.1 breaks the
  container deployment.
- ``github`` enforces read-only server-side via X-MCP-Readonly plus a scoped
  X-MCP-Toolsets header; client-side per-agent tool filtering is the second,
  deliberately redundant layer.
- ``conversation`` (Phase 3) is the Conversation FastMCP server — read-only by
  construction (single search_messages tool) and bound to 127.0.0.1; never
  expose a write tool there (PHASE_3.md §5/§8).
- ``tool_name_prefix`` stays at its default (False). Do not add prefix-stripping
  or fuzzy tool-name-matching to scoped(); CRG's own tool names already contain
  underscores as part of the real name, so naive stripping corrupts them.
- ``handle_tool_errors`` stays at its default (True): an MCP tool failure comes
  back as a ToolMessage(status="error") for the agent to handle instead of
  crashing the review.
"""

import asyncio
import logging

from langchain_mcp_adapters.client import MultiServerMCPClient

from infrastructure.config import settings

logger = logging.getLogger(__name__)

# Prevent concurrent rebuilds when multiple requests hit a dead server at once.
_rebuild_lock = asyncio.Lock()


def build_mcp_client(
    github_pat_override: str | None = None,
    jira_headers: dict[str, str] | None = None,
) -> MultiServerMCPClient:
    """Build a MultiServerMCPClient with optional per-review overrides.

    When ``github_pat_override`` is provided (from the credential vault),
    it replaces the global ``settings.github_pat`` for this client instance.

    When ``jira_headers`` is provided (from the credential vault via
    build_jira_headers_for_user()), it replaces the global atlassian
    connection headers. This injects per-user X-Atlassian-Jira-Url and
    Authorization headers into every MCP request to mcp-atlassian.
    """
    github_pat = github_pat_override or settings.github_pat
    atlassian_config: dict = {
        "transport": "streamable_http",
        "url": settings.atlassian_mcp_url,
    }
    if jira_headers:
        atlassian_config["headers"] = jira_headers
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
                    "Authorization": f"Bearer {github_pat}",
                    "X-MCP-Readonly": "true",
                    "X-MCP-Toolsets": "repos,issues,pull_requests,code_security,dependabot,actions",
                },
            },
            "atlassian": atlassian_config,
            "context7": {
                "transport": "streamable_http",
                "url": "https://mcp.context7.com/mcp",
                "headers": (
                    {"CONTEXT7_API_KEY": settings.context7_api_key}
                    if settings.context7_api_key
                    else {}
                ),
            },
            "conversation": {
                "transport": "streamable_http",
                "url": settings.conversation_mcp_url,
            },
        }
    )


async def rebuild_mcp_client(
    github_pat_override: str | None = None,
    jira_headers: dict[str, str] | None = None,
) -> MultiServerMCPClient:
    """Build a fresh MultiServerMCPClient and verify atlassian connectivity.

    Called by the review route (D-12) when the health probe fails.  Uses a
    lock to prevent concurrent rebuilds from multiple concurrent requests.
    On success returns the new client; on failure returns a newly-built
    client anyway (tools will be skipped by scope_agent_tools' degraded path).

    ``github_pat_override``: when set (from the credential vault), used
    instead of the global ``settings.github_pat`` for this client.
    ``jira_headers``: when set (from the credential vault), injected into
    every MCP request to mcp-atlassian for per-user Jira auth/URL.
    """
    async with _rebuild_lock:
        new_client = build_mcp_client(
            github_pat_override=github_pat_override,
            jira_headers=jira_headers,
        )
        try:
            await new_client.get_tools(server_name="atlassian")
            logger.info("MCP client rebuilt - atlassian reachable")
        except Exception:
            logger.warning("MCP client rebuilt - atlassian still unreachable (degraded mode)")
        return new_client


def scoped(tools: list, allowed_names: set[str]) -> list:
    """Return only the tools whose names are in allowed_names."""
    return [t for t in tools if t.name in allowed_names]
