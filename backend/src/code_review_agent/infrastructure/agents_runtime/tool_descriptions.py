"""One-line tool-description overrides for the scoped MCP tools.

MCP tools ship with verbose multi-paragraph descriptions (CRG's in
particular, some ~500 tokens). Because the full description is re-sent to the
model on EVERY turn of EVERY subagent that carries the tool, they dominate the
token budget of a review run.

The overrides are applied in ``tool_scoping._wrap_with_events``, which wraps
every scoped MCP tool that reaches a subagent — the single choke point every
subagent tool passes through. (The deepagents ``HarnessProfile.tool_description_overrides``
hook was tried first but does not propagate to declarative subagent stacks in
the installed version, so the wrapper substitution is the reliable mechanism.)
These terse replacements cut the per-request schema payload by roughly 70-80%
while keeping enough information to pick the right tool. Parameter guidance
lives in the args_schema, which is untouched.

Keys MUST match the live MCP tool names exactly — a stale key is a silent
no-op. All names below were re-verified against the live servers: CRG via the
connected code-review-graph server, GitHub via a read-only MCP probe of
https://api.githubcopilot.com/mcp/ (30 tools, all 12 names used by
AGENT_TOOL_PLAN confirmed), Atlassian against mcp-atlassian 0.23.0, Context7
against the remote server.
"""

from typing import Final

TOOL_DESCRIPTION_OVERRIDES: Final[dict[str, str]] = {
    # --- CRG (code-review-graph) ---
    "get_review_context_tool": "Get a token-efficient review context (impact analysis + source snippets) for the changed files.",
    "query_graph_tool": "Run a graph query (callers/callees/imports/tests/children, etc.) on a target node or file.",
    "get_architecture_overview_tool": "High-level architecture overview of the codebase, organized by community.",
    "find_large_functions_tool": "Find functions, classes, or files exceeding a line-count threshold.",
    "get_knowledge_gaps_tool": "Find untested hotspots, isolated nodes, and thin communities.",
    "get_impact_radius_tool": "Blast radius of the changed files (impacted functions, classes, files).",
    "get_bridge_nodes_tool": "Top architectural chokepoints by betweenness centrality.",
    "get_surprising_connections_tool": "Unexpected cross-community coupling (surprise-scored edges).",
    "detect_changes_tool": "Risk-scored, priority-ordered review guidance for the git diff.",
    "list_flows_tool": "List execution flows in the codebase, sorted by criticality.",
    "get_flow_tool": "Get the call path of one execution flow (optionally with source).",
    "get_affected_flows_tool": "Execution flows that pass through the changed files.",
    "get_hub_nodes_tool": "Most-connected (highest-degree) nodes in the codebase.",
    "traverse_graph_tool": "BFS/DFS exploration from a matching node, bounded by a token budget.",
    "semantic_search_nodes_tool": "Semantic or keyword search over code-entity names.",
    "refactor_tool": "Preview rename / dead-code detection / refactoring suggestions (preview only, never applies).",
    "get_docs_section_tool": "Fetch one section of the plugin's LLM-optimized documentation.",
    # --- GitHub (read-only) ---
    "pull_request_read": "Read a pull request's details (diff, metadata) from a GitHub repo.",
    "get_file_contents": "Get file or directory contents from a GitHub repo.",
    "list_commits": "List commits of a branch in a GitHub repo.",
    "search_code": "GitHub code search across repositories.",
    "list_code_scanning_alerts": "List existing CodeQL code-scanning alerts in a repo.",
    "get_code_scanning_alert": "Get details of one code-scanning alert.",
    "list_dependabot_alerts": "List Dependabot security alerts for a repo.",
    "get_dependabot_alert": "Get details of one Dependabot alert.",
    "actions_list": "List GitHub Actions resources (workflows, runs).",
    "actions_get": "Get details of a specific GitHub Actions resource.",
    "get_job_logs": "Get logs for a GitHub Actions workflow job.",
    # --- Atlassian (read-only) ---
    "jira_get_issue": "Read a Jira issue by its key.",
    "confluence_search": "Search Confluence pages.",
    "confluence_get_page": "Read a Confluence page by ID.",
    # --- Context7 ---
    "resolve-library-id": "Resolve a library name to a Context7 library ID.",
    "query-docs": "Query current Context7 documentation for a library ID.",
}
