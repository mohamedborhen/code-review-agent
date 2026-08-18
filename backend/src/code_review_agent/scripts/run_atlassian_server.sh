#!/usr/bin/env bash
# Launch the self-hosted mcp-atlassian server for local development.
#
# Auth env vars are read by the mcp-atlassian process itself (NOT via
# MultiServerMCPClient headers): JIRA_URL / JIRA_USERNAME / JIRA_API_TOKEN
# and CONFLUENCE_URL / CONFLUENCE_USERNAME / CONFLUENCE_API_TOKEN.
#
# Read-only is enforced server-side so review agents can never write to
# Jira/Confluence (mirrors the GitHub X-MCP-Readonly enforcement).
#
# ALLOW_GLOBAL_CRED_FALLBACK: mcp-atlassian's single-user global-credential
# fallback gate. Since 0.23.0 its UserTokenMiddleware rejects unauthenticated
# HTTP MCP requests (401) unless this is set, because a no-token caller would
# otherwise transact as the operator. This applies to ANY server-side auth type
# (our Cloud API tokens included), NOT just mTLS. We keep it true because our
# client sends no per-request Atlassian headers (creds live in this process's
# env). Revisit only if a future phase moves to per-user auth headers.
#
# THIS ENV IS LOAD-BEARING — the 2026-08-18 E2E incident (session 115):
# launching `uvx mcp-atlassian --transport streamable-http --port 9000` WITHOUT
# these exports + `--env-file .env` made UserTokenMiddleware 401 every MCP
# request, so `MultiServerMCPClient.get_tools(server_name="atlassian")` raised
# an ExceptionGroup and `POST /review` returned 500 ("unhandled errors in a
# TaskGroup"). The server banner printed "FastMCP 3.4.7" (the framework
# version), which is NOT the mcp-atlassian version — the package is pinned at
# 0.23.0 below. Always launch via this script (or the compose service); a bare
# `uvx` invocation is not equivalent.
set -euo pipefail

# Server-side security boundaries (mirror the GitHub X-MCP-Readonly enforcement).
# READ_ONLY_MODE blocks every write action; ENABLED_TOOLS is an exact-name
# allowlist enforced at BOTH tools/list and call time (see _is_tool_authorized
# in mcp_atlassian/servers/main.py) — review agents can never reach the ~38
# other Jira tools or ~20 other Confluence tools, write or read.
export READ_ONLY_MODE=true
export ALLOW_GLOBAL_CRED_FALLBACK=true
# Full 58-tool set (jira_* + confluence_*); mcp-atlassian v0.22+ will otherwise
# default to only 6 core toolsets once the default flips.
export TOOLSETS=all
export ENABLED_TOOLS="jira_get_issue,confluence_search,confluence_get_page"

exec uvx mcp-atlassian@0.23.0 --env-file .env -v --transport streamable-http --port 9000
