#!/usr/bin/env bash
# Launch the Conversation FastMCP server for local development (Phase 3).
#
# Binds to 127.0.0.1 only (PHASE_3.md §9.4); the port/path come from
# CONVERSATION_MCP_URL (default http://127.0.0.1:9001/mcp).
set -euo pipefail

exec python -m infrastructure.mcp_clients.servers.conversation_server
