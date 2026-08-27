// Human-readable labels and icons for all known tool names.
// Raw tool names are hidden by default and shown in expandable details.

export interface ToolMeta {
  label: string;
  icon: string;
  category: "graph" | "github" | "atlassian" | "context" | "llm" | "agent";
}

const TOOL_MAP: Record<string, ToolMeta> = {
  // CRG graph tools
  "get_review_context_tool":     { label: "Reviewing code context",       icon: "account_tree",     category: "graph" },
  "query_graph_tool":            { label: "Querying code graph",          icon: "query_stats",      category: "graph" },
  "get_architecture_overview_tool": { label: "Analyzing architecture",    icon: "architecture",     category: "graph" },
  "find_large_functions_tool":   { label: "Finding large functions",      icon: "straighten",       category: "graph" },
  "get_knowledge_gaps_tool":     { label: "Detecting knowledge gaps",     icon: "question_mark",    category: "graph" },
  "get_impact_radius_tool":      { label: "Measuring impact radius",      icon: "radar",            category: "graph" },
  "get_bridge_nodes_tool":       { label: "Finding bridge nodes",         icon: "hub",              category: "graph" },
  "get_surprising_connections_tool": { label: "Finding hidden connections", icon: "link",            category: "graph" },
  "detect_changes_tool":         { label: "Detecting changes",            icon: "difference",       category: "graph" },
  "list_flows_tool":             { label: "Listing data flows",           icon: "swap_vert",        category: "graph" },
  "get_flow_tool":               { label: "Tracing data flow",            icon: "timeline",         category: "graph" },
  "get_affected_flows_tool":     { label: "Finding affected flows",       icon: "timeline",         category: "graph" },
  "get_hub_nodes_tool":          { label: "Finding hub nodes",            icon: "account_tree",     category: "graph" },
  "traverse_graph_tool":         { label: "Traversing graph",             icon: "explore",          category: "graph" },
  "semantic_search_nodes_tool":  { label: "Searching code semantically",  icon: "search",           category: "graph" },
  "refactor_tool":               { label: "Suggesting refactoring",       icon: "code",             category: "graph" },
  "get_docs_section_tool":       { label: "Reading documentation",        icon: "menu_book",        category: "graph" },

  // GitHub MCP tools
  "pull_request_read":           { label: "Reading pull request",         icon: "merge_type",       category: "github" },
  "get_file_contents":           { label: "Reading file contents",        icon: "description",      category: "github" },
  "list_commits":                { label: "Listing commits",              icon: "commit",           category: "github" },
  "search_code":                 { label: "Searching code",               icon: "search",           category: "github" },
  "list_code_scanning_alerts":   { label: "Listing code scanning alerts", icon: "bug_report",       category: "github" },
  "get_code_scanning_alert":     { label: "Reading code scanning alert",  icon: "bug_report",       category: "github" },
  "list_dependabot_alerts":      { label: "Listing Dependabot alerts",    icon: "security",         category: "github" },
  "get_dependabot_alert":        { label: "Reading Dependabot alert",     icon: "security",         category: "github" },
  "actions_list":                { label: "Listing CI workflows",         icon: "play_circle",      category: "github" },
  "actions_get":                 { label: "Reading CI workflow",          icon: "play_circle",      category: "github" },
  "get_job_logs":                { label: "Reading CI job logs",          icon: "terminal",         category: "github" },

  // Atlassian tools
  "jira_get_issue":              { label: "Reading Jira issue",           icon: "task",             category: "atlassian" },
  "confluence_search":           { label: "Searching Confluence",         icon: "search",           category: "atlassian" },
  "confluence_get_page":         { label: "Reading Confluence page",      icon: "article",          category: "atlassian" },

  // Context7 tools
  "resolve-library-id":          { label: "Resolving library docs",       icon: "library_books",    category: "context" },
  "query-docs":                  { label: "Querying documentation",       icon: "menu_book",        category: "context" },

  // Conversation tools
  "search_messages":             { label: "Recalling past conversations", icon: "history",          category: "context" },

  // LLM / agent internal
  "task":                        { label: "Delegating to specialist",     icon: "smart_toy",        category: "agent" },
  "SubagentReport":              { label: "Compiling findings",           icon: "summarize",        category: "agent" },
};

const CATEGORY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  graph:      { bg: "#00f5ff15", text: "#00f5ff", border: "#00f5ff40" },
  github:     { bg: "#8b949e15", text: "#8b949e", border: "#8b949e40" },
  atlassian:  { bg: "#0052cc15", text: "#579DFF", border: "#0052cc40" },
  context:    { bg: "#84949515", text: "#849495", border: "#84949540" },
  agent:      { bg: "#a78bfa15", text: "#a78bfa", border: "#a78bfa40" },
  llm:        { bg: "#e7c42715", text: "#e7c427", border: "#e7c42740" },
};

export function getToolMeta(toolName: string): ToolMeta {
  return TOOL_MAP[toolName] ?? { label: toolName, icon: "build", category: "agent" };
}

export function getCategoryStyle(category: string) {
  return CATEGORY_STYLES[category] ?? CATEGORY_STYLES.agent;
}
