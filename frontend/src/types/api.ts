// Final Phase 5 — exact contracts verified against live backend source.
// §2 was audited with file:line citations; §3 lists what does NOT exist.
// OAuth is deleted — no /auth/* route, no redirect, no token exchange.

export type RequestType =
  | "review" | "security_question" | "compliance_question"
  | "performance_question" | "impact_question" | "explain_question"
  | "any_question";

export interface Branch { name: string; sha: string; protected: boolean; }
export interface BranchesResponse { repo_id: string; branches: Branch[]; }
export interface RegisterRepoResponse { status: "accepted"; repo_id: string; }

// POST /api/v1/conversations — exactly 4 keys (conversation.py:64-69)
export interface CreateConversationResponse {
  conversation_id: number;
  repo_id: string;
  user_id: string;
  status: string; // "active" on create
}

// POST /api/v1/conversations/{conversation_id}/message
// Different tool-call shape from ReviewToolCallItem
export interface ConversationToolCall {
  message_id: number;
  tool_name: string;
  tool_input: string | null;
  tool_output: string | null;
  tool_latency_ms: number | null;
  tool_status: "success" | "error" | null;
  id: number | null;
}

export interface RecallResult {
  message_id: number;
  role: string;
  snippet: string;
  created_at: string | null;
  score: number;
}

export interface MessageTurnResponse {
  conversation_id: number;
  user_message: string;
  context: {
    conversation_id: number;
    results: RecallResult[];
    error: string | null;
    latency_ms: number;
  } | null;
  tool_calls: ConversationToolCall[];
}

// FINAL /repos credential contract (decision 4) — write-only vault fields
export interface RepoRegistrationRequest {
  repo_url: string;           // required, https://github.com/owner/repo[.git]
  repo_id: string;            // required, "owner/repo" must match repo_url
  user_id: string;            // required, client-generated uuid (decision 2)
  display_name?: string | null;
  github_pat?: string | null;   // required for private, optional public — encrypted server-side, never returned
  webhook_secret?: string | null; // per-repo HMAC secret — encrypted, manual GitHub webhook
}
export interface RepoRegistrationResponse {
  status: "accepted";
  repo_id: string;
  credential_stored: boolean; // true if vault row written
}

// Jira per-user Basic (decision 4) — sent as Authorization: Basic base64(email:token)
export interface JiraCredentialRequest {
  user_id: string;
  repo_id: string;         // repository ID, or "*" for all registered repos
  jira_url: string;      // https://*.atlassian.net
  jira_email: string;
  jira_api_token: string; // write-only, Fernet encrypted
}
export interface JiraCredentialResponse { stored: boolean; }
export interface JiraValidateResponse { ok: boolean; account_id?: string; error?: string; }

// Identity — application identity only, not authentication (decision 2)
export interface IdentityState {
  user_id: string;       // uuid v4 generated client-side once, persisted in localStorage
  display_name: string;  // prompted on first use
  created_at: string;    // ISO
}

export interface ReviewRequest {
  repo_id: string;
  graph_commit_hash?: string | null;
  branch?: string | null;
  request_type: RequestType;
  diff_content?: string | null; // always omitted in Phase 5 — no UI path, DiffInjectionMiddleware no-ops
  question?: string | null;
  conversation_id?: number | null;
  user_id?: string | null;
}
export interface TimelineEntry { kind: "llm" | "tool"; name: string; duration_ms: number; }
export interface ReviewResponse {
  review_session_id: number;
  result: string; // JSON string — must JSON.parse(), vs GET returns dict
  timeline: Record<string, TimelineEntry[]>;
  timeline_text: string;
}
// severity is OPEN string, not union — live review returned 6 values
export interface AgentFinding {
  severity: string; // critical > high > warning > medium > low > info, unknown -> info
  confidence: number;
  title: string;
  description: string;
  evidence: string[];
  recommendation: string;
}
export interface AggregatedOutput {
  agent_name: string;
  findings: AgentFinding[];
  parse_status: "ok" | "parse_failed" | "empty_output" | "fallback_from_specialists";
}
export interface RunningReviewResponse {
  review_session_id: number | null;
  status: string | null;
  created_at?: string | null; // absent on no-match, not null
}
export interface ReviewToolCallItem {
  agent_name: string;
  tool_name: string;
  tool_input: string | null;
  tool_output: string | null;
  tool_latency_ms: number | null;
  tool_status: "success" | "error" | null;
  created_at: string | null; // unordered — sort client-side
}
export interface ReviewStatusResponse {
  review_session_id: number;
  status: "running" | "completed" | "failed" | null;
  repo_id: string;
  request_type: RequestType;
  created_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error: string | null;
  result: AggregatedOutput | null;
  tool_calls: ReviewToolCallItem[];
}

// BLOCKING SPIKE NOTE (item 5): mcp_atlassian@0.23.0 Basic branch does url: base_config.url
// (dependencies.py:697). Spike must probe live header round-trip with dummy global JIRA_URL
// before wiring per-user headers — if placeholder leaks, apply user_config.url = user_jira_url.
// MINIMUM PAT SCOPES (item 6): repo (or contents:read+pull-requests:read+metadata:read)
// + security_events:read + actions:read for exactly the 12 read-only tools in tool_lists.py:36-63 + list_branches.
// LEAK TEST (item 7): 7 assertions in tests/test_credential_leak.py — no credential in response/logs/.git/config/localStorage/IndexedDB, token-in-URL rejected.
// OAUTH SCAN (item 8): fail if outside vendor cache any of \boauth\b, OAuth, github.*oauth, atlassian.*oauth, /auth/atlassian, ALLOW_GLOBAL_CRED_FALLBACK, oauth toolset.
