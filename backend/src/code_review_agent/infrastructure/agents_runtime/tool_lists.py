"""Centralized per-agent tool-name lists (exact names from PHASE_2.md).

One file so the DoD's "verify GitHub tool names against the live registry" pass
is a single-file edit, not a hunt through runtime code. The GitHub names below
are transcribed from PHASE_2.md and MUST be re-verified against the live server
(e.g. ``mcpcurl tools --help``) once a real GITHUB_PAT is available — see the
OPENCODE.md blocker. CRG/Context7 names come from PHASE_2.md; the Atlassian
names were verified against the live mcp-atlassian server (0.23.0) and its
source.
"""

from typing import Final

CRG: Final[set[str]] = {
    "get_review_context_tool",
    "query_graph_tool",
    "get_architecture_overview_tool",
    "find_large_functions_tool",
    "get_knowledge_gaps_tool",
    "get_impact_radius_tool",
    "get_bridge_nodes_tool",
    "get_surprising_connections_tool",
    "detect_changes_tool",
    "list_flows_tool",
    "get_flow_tool",
    "get_affected_flows_tool",
    "get_hub_nodes_tool",
    "traverse_graph_tool",
    "semantic_search_nodes_tool",
    "refactor_tool",
    "get_docs_section_tool",
}

# GitHub MCP tool names — DO NOT trust these unverified. Re-check against the
# live registry before relying on them (GitHub has been consolidating names).
GITHUB: Final[dict[str, set[str]]] = {
    "compliance": {
        "pull_request_read",
        "get_file_contents",
        "list_commits",
        "search_code",
    },
    "security": {
        "pull_request_read",
        "get_file_contents",
        "list_code_scanning_alerts",
        "get_code_scanning_alert",
        "list_dependabot_alerts",
        "get_dependabot_alert",
    },
    "performance": {
        "pull_request_read",
        "get_file_contents",
        "list_commits",
    },
    "regression": {
        "pull_request_read",
        "get_file_contents",
        "actions_list",
        "actions_get",
        "get_job_logs",
    },
}

# Exact mcp-atlassian tool names (verified against the live 0.23.0 server).
# mcp-atlassian additionally enforces these server-side via ENABLED_TOOLS plus
# READ_ONLY_MODE — see run_atlassian_server.sh / docker-compose.yaml. This
# client-side set is the second, deliberately redundant layer: even a misconfig
# in the launch env cannot widen an agent's tools beyond what's listed here.
ATLASSIAN_COMPLIANCE: Final[set[str]] = {
    "jira_get_issue",
    "confluence_search",
    "confluence_get_page",
}
ATLASSIAN_FIX_SUGGESTION: Final[set[str]] = {
    "confluence_search",
    "confluence_get_page",
}

# Per-agent tool scoping. A value of None means "all tools from that server"
# (used only for Context7, which is read-only documentation lookup by design).
AGENT_TOOL_PLAN: Final[dict[str, dict[str, set[str] | None]]] = {
    "compliance": {
        "crg": {
            "get_review_context_tool",
            "query_graph_tool",
            "get_architecture_overview_tool",
            "find_large_functions_tool",
            "get_knowledge_gaps_tool",
        },
        "github": GITHUB["compliance"],
        "atlassian": ATLASSIAN_COMPLIANCE,
        "context7": set(),
    },
    "security": {
        "crg": {
            "get_impact_radius_tool",
            "get_bridge_nodes_tool",
            "get_surprising_connections_tool",
            "detect_changes_tool",
        },
        "github": GITHUB["security"],
        "atlassian": set(),
        "context7": {"resolve-library-id", "query-docs"},
    },
    "performance": {
        "crg": {
            "list_flows_tool",
            "get_flow_tool",
            "get_affected_flows_tool",
            "get_hub_nodes_tool",
        },
        "github": GITHUB["performance"],
        "atlassian": set(),
        "context7": None,
    },
    "regression": {
        "crg": {
            "get_impact_radius_tool",
            "detect_changes_tool",
            "get_affected_flows_tool",
            "traverse_graph_tool",
            "get_knowledge_gaps_tool",
        },
        "github": GITHUB["regression"],
        "atlassian": set(),
        "context7": set(),
    },
    "fix_suggestion": {
        "crg": {
            "semantic_search_nodes_tool",
            "refactor_tool",
            "get_docs_section_tool",
        },
        "github": set(),
        "atlassian": ATLASSIAN_FIX_SUGGESTION,  # confluence read tools only — no Jira, no writes
        "context7": None,
    },
}
