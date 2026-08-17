# Phase 2 — Multi-Agent Review System (No LangMem, No Conversation Memory)

**Read this whole file before writing any code.** Every ambiguity that could cause guessing has been resolved to a specific, verified decision below — do not substitute your own default. Where a library's exact API is quoted, it was pulled from that library's own current documentation, not from training-data memory.

---

## What Phase 1 Already Built (do not redo, do not modify)

CRG is running (`code-review-graph serve --http --port 5555`), a repo gets cloned/synced on webhook, and the graph stays current. `PHASE_1.md`, `AGENTS.md`, `OPENCODE.md`, and the three `.opencode/agents/` files from Phase 1 remain the source of truth for that layer — nothing here replaces them.

## Full Project Context (context only)

Full system: React frontend, FastAPI backend, conversation memory in PostgreSQL (no vector/embedding search — a dedicated MCP server with curated, parameterized query tools instead, per project decision) with LangMem summarization, a Context Agent doing structured/keyword lookups over history rather than semantic similarity search. **None of that is this phase.** This phase builds the multi-agent review core: one request in, one structured result out, no memory of past turns.

## Scope for This Phase

**Build:**
- 7 agents: Orchestrator, Compliance, Security, Performance, Regression, Fix Suggestion, Aggregator.
- `AgentInput`/`AgentFinding`/`AgentOutput` contracts.
- The Routing Policy.
- MCP connections: CRG (already running), GitHub, Atlassian (Jira + Confluence), Context7.
- The event schema (thinking/tool_call/tool_result/final) — log it, no UI needed yet.
- One endpoint: `POST /review` — async, request-response, not streaming.
- `review_session` / `agent_executions` tables (audit trail — this is not conversation memory, keep it).

**Do not build:** LangMem MCP, Context Agent, conversation persistence (`messages`/`conversation_summary` tables), React frontend, streaming, anything beyond `build_or_update_graph_tool` that isn't already covered by this file's per-agent CRG tool lists.

---

## The 5-Layer Architecture (unchanged from Phase 1)

| Layer | Contains | Depends on |
|---|---|---|
| 1. Presentation | (not built yet) | — |
| 2. API / Gateway | FastAPI routes | Layer 3 |
| 3. Application | Use-case services (review orchestration, routing) | Layer 4 |
| 4. Domain | Contracts, entities, ports — pure Python | nothing |
| 5. Infrastructure | Agent runtimes, MCP clients, LLM provider | Implements Layer 4 |

**Hard rule, same as Phase 1:** `domain/` never imports `deepagents`, `langchain_mcp_adapters`, `fastapi`, or any concrete SDK.

**Async/sync note:** unlike Phase 1, this layer is legitimately async-heavy — `deepagents`/LangGraph and `langchain_mcp_adapters` are async-native throughout. Domain **entities** stay plain dataclasses either way (no I/O), but Domain **ports** for review execution should be defined as `async def` this time — do not force a sync bridge here the way Phase 1 did for the MCP SDK; that was specifically because Phase 1's Application layer ran inside sync `BackgroundTasks`. This phase's `/review` endpoint can `await` directly.

---

## Orchestration Framework — Verified API

**deepagents**, built on LangGraph. Confirmed from the library's own docs:

```python
from deepagents import create_deep_agent

compliance_agent = {
    "name": "compliance",
    "description": "Checks a diff against team coding standards and ticket scope",
    "system_prompt": COMPLIANCE_SYSTEM_PROMPT,
    "tools": compliance_tools,       # see MCP Tool Loading below
}
# ... one dict per subagent ...

agent = create_deep_agent(
    model=settings.review_model,  # required setting, no default — see config.py note below
    system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
    subagents=[compliance_agent, security_agent, performance_agent, regression_agent, fix_suggestion_agent],
)

result = await agent.ainvoke({"messages": [{"role": "user", "content": review_request}]})
```

Each subagent dict's `tools` list must contain LangChain `BaseTool` objects, not raw MCP tool names or dicts — see the loading pattern below for how those are produced.

**Verified implementation notes (what the code actually does):**
- **One root deep agent, not two.** The Orchestrator and Aggregator are a single `create_deep_agent` root whose `system_prompt` is `orchestrator.md` + `aggregator.md` concatenated: the root's classify phase is the Orchestrator, its synthesis phase the Aggregator. `response_format=SubagentReport` is set on the root and deepagents propagates it to every subagent, so each subagent's `ToolMessage` content is the JSON serialization of a `SubagentReport` (that is what per-agent audit rows are parsed from).
- **Subagents built by per-agent builder functions** (`subagents/*_runtime.py`, each `build_*_spec(mcp_client, store)` returning a plain dict literal — not a typed class). All five specialists are registered whenever the routed set is non-empty (`fix_suggestion` is available on demand; the orchestrator decides whether to use it); for an empty routed set (`explain_question`) `subagents=None` — no subagents are constructed at all.
- **Safety harness profile (`harness_profile.py`).** `create_deep_agent` always injects a built-in tool suite (`ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`, `execute`); the `tools` parameter is strictly additive and cannot remove them. A `HarnessProfile` with `excluded_tools` strips all eight and disables the general-purpose subagent. The profile is registered under EVERY key deepagents may resolve (the raw model spec AND the pre-built path's resolved `provider:identifier`), so no agent — root or subagent — ever holds a write/execute-capable built-in tool. `task` is deliberately retained: the orchestrator needs it to delegate.
- **Per-agent capture (`capture.py` + `middleware.py`).** Each subagent spec gets a `SubagentCaptureMiddleware`, which wraps every model call to time it (real per-LLM-call `duration_ms` into a `CaptureStore`) and emit the subagent's own reasoning and attempted/rejected tool calls as events; the model id is recorded per agent and written to the `AgentExecution.model` column (reconciled to the canonical `settings.review_model` spec via `canonical_model_label` when they match). The root gets `RootTimingMiddleware` (times each root/orchestrator LLM call) and `DiffInjectionMiddleware` (injects the canonical diff into every `task` tool-call description — see the orchestrator note above). After a run the route drains `CaptureStore.consume_timeline()` into the `timeline`/`timeline_text` response fields.
- **Resilience (`middleware.py` + `orchestrator_runtime.py`).** `TransientRetryMiddleware` (root) and `_run_with_retry` (root + every subagent) retry transient failures — 429/5xx/rate-limit/socket-timeout provider errors and deepagents structured-output parse failures — with bounded retries (3 for model-call level, 1 for report-parse level). A weak-model empty-native-output 500 was observed once and is gone after the parse-level retry. Unrelated exceptions propagate to the 500 boundary immediately (the route still writes the audit row before returning 500).
- **Tolerant report parsing (in `orchestrator_runtime.py`).** The configured free-tier model drifts from the exact report shape run to run (markdown-fenced JSON, `<subagent_report>` XML wrappers, nested `{"security_review": {"findings": [...]}}`, `violations`/`security_findings` aliases, string confidences, `location`/`risk_score`/`recommendations` synonyms). Strict `SubagentReport` validation is attempted first; `_extract_json`/`_findings_list`/`_coerce_finding`/`_coerce_report` recover the rest so per-agent `AgentExecution` rows carry real findings.

**`config.py` addition:** `review_model: str` with **no default value** — force it via env var (`REVIEW_MODEL=<provider>:<model>`). It is the single model spec for the whole multi-agent system. deepagents resolves it via langchain's `init_chat_model`, which dispatches by provider prefix (`groq:`, `openrouter:`, `google_genai:`, `openai:`, `anthropic:`, `deepseek:`, `ollama:`, ...), so switching providers is a config + package + API-key change, never a code change. Do not hardcode any specific dated model snapshot in code; that just relocates the staleness problem instead of removing it. The provider's langchain integration package (see `requirements.txt`) and its API key env var (e.g. `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_HOST`) must be present — only the one matching `REVIEW_MODEL` is required.

**`config.py` additions beyond `review_model`** (all env-configurable, nothing hardcoded):
- `review_max_tokens: int = 8192` (`REVIEW_MAX_TOKENS`) — output-token budget forwarded to the provider as `max_tokens` (raised from the original default of 2000 for the NVIDIA Nemotron 49B demo model, which burns completion tokens on `reasoning_content` — a 2000 cap truncated a long-reasoning turn into an empty assistant message → empty subagent report). Left unset, deepagents/openrouter resolve to the model's full output window (16k for gpt-4o-mini), which the OpenRouter free tier rejects.
- `review_timeout: int = 600` (`REVIEW_TIMEOUT`) — per-model-call timeout forwarded as `timeout`, replacing a hardcoded 240s that surfaced as "Timeout on reading data from socket" on a free-tier long-reasoning turn.
- `atlassian_mcp_url` (`ATLASSIAN_MCP_URL`) — the mcp-atlassian endpoint; docker-compose overrides to `http://mcp-atlassian:9000/mcp` for the same reason `crg_server_url` is a setting.
- Jira/Confluence auth (`JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, `CONFLUENCE_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN`) — read by the mcp-atlassian process, never sent as client headers.
- `model_config` uses `extra="ignore"`: the shared `.env` also carries keys owned by other processes (LLM provider keys, mcp-atlassian server vars) that are not `Settings` fields; pydantic-settings defaults to `extra="forbid"`, which would crash boot.
- The `.env` file is located by `_resolve_env_file()` in `config.py`: it walks from the module path up to the filesystem root (and then CWD) and takes the first `.env` found — so the repo-root `.env` is found regardless of the launch CWD. `load_dotenv` runs *before* `Settings()` construction, and `Settings` is also constructed with `_env_file` pointing at that same resolved path, so process env vars and the `.env` file are both honored (process env wins where both set it).

Both caps are delivered to deepagents via a `ProviderProfile` registered in `_ensure_review_provider_profile()` under the exact `settings.review_model` key, so the model stays a STRING while `init_chat_model` receives `max_tokens`/`timeout`.

## MCP Tool Loading — Verified API

**`langchain-mcp-adapters`**, via `MultiServerMCPClient`. One shared client for the whole backend, one connection per server, tools fetched and then filtered per agent in plain Python — `get_tools()` returns everything from a server; there is no built-in per-tool-name filter, so agent-level scoping is your own filtering step, not a library feature.

**Lifespan management — do not construct this per-request.** Four HTTP connection setups on every single `POST /review` call is real, avoidable latency. Build it once at FastAPI startup and reuse it:

```python
# infrastructure/api/main.py (or wherever the FastAPI app is constructed)
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.mcp_client = MultiServerMCPClient({...})   # config below
    yield
    # MultiServerMCPClient does not require explicit teardown as of the current SDK version — verify against its docs if this changes

app = FastAPI(lifespan=lifespan)
```

Routes and `agents_runtime/` code access it via `request.app.state.mcp_client`, not by constructing a new one.

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

mcp_client = MultiServerMCPClient({
    "crg": {
        "transport": "streamable_http",
        "url": settings.crg_server_url,   # Phase 1's setting — env-configurable; localhost:5555 by default, docker-compose overrides to http://crg-server:5555/mcp. Do not hardcode 127.0.0.1 here or the container deployment breaks.
    },
    "github": {
        "transport": "streamable_http",
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {
            "Authorization": f"Bearer {settings.github_pat}",
            "X-MCP-Readonly": "true",       # review agents only ever read — never write via this server
            "X-MCP-Toolsets": "repos,issues,pull_requests,code_security,dependabot,actions",
        },
    },
    "atlassian": {
        "transport": "streamable_http",
        "url": "http://127.0.0.1:9000/mcp",   # self-hosted mcp-atlassian, see below
    },
    "context7": {
        "transport": "streamable_http",
        "url": "https://mcp.context7.com/mcp",
        "headers": {"CONTEXT7_API_KEY": settings.context7_api_key} if settings.context7_api_key else {},
    },
    # tool_name_prefix defaults to False — leave it unset. If it's ever set to True,
    # every allowed_names set below must be updated to the prefixed names, or scoping
    # silently breaks. Do not "fix" this by fuzzy-stripping prefixes from tool names —
    # CRG's own tool names already contain underscores as part of their real name
    # (e.g. get_review_context_tool), so a naive split-based strip corrupts real names
    # rather than removing a prefix that, by default, was never added.
})

crg_tools = await mcp_client.get_tools(server_name="crg")
github_tools = await mcp_client.get_tools(server_name="github")
atlassian_tools = await mcp_client.get_tools(server_name="atlassian")
context7_tools = await mcp_client.get_tools(server_name="context7")

def scoped(tools: list, allowed_names: set[str]) -> list:
    return [t for t in tools if t.name in allowed_names]
```

**Known trade-off — session-per-invocation (accepted for this phase).** `MultiServerMCPClient.get_tools()` does not keep one session open per server. Per the library's own docs, a new session is created for each tool invocation unless the `session()` context manager is explicitly used. With ~5 agents × 3–5 tool calls per review, that's roughly 15–25 session creations per `/review` call. This is accepted for Phase 2 — the lifespan-level client reuse above is the optimization that actually matters here (avoiding four fresh HTTP connection setups per request). Revisit with explicit `session()` reuse only if profiling shows session overhead is a real bottleneck, not preemptively.

**Design choice — `handle_tool_errors` (left at its default).** `MultiServerMCPClient`/`load_mcp_tools` default to `handle_tool_errors=True`: an MCP tool execution error comes back as a `ToolMessage` with `status="error"` instead of raising, so the calling agent sees the failure and can retry or adjust rather than the review crashing outright. This is relied on, not accidental — do not set `handle_tool_errors=False` anywhere in this phase.

**Verified tooling additions (files that make the scoping actually work):**
- **`tool_lists.py`** — the single source of per-agent tool names: `CRG`, `GITHUB[agent]`, `ATLASSIAN_COMPLIANCE`/`ATLASSIAN_FIX_SUGGESTION`, and `AGENT_TOOL_PLAN[agent] = {server: allowed_names}` where a value of `None` means "all tools from that server" (used only for Context7 — read-only documentation lookup by design) and `set()` means "none from that server". One file so the DoD's "verify tool names against the live registry" pass is a single-file edit.
- **`tool_descriptions.py`** — one-line description overrides for every scoped tool. MCP tools ship verbose multi-paragraph descriptions (CRG's ~500 tokens) that are re-sent on every turn of every carrying agent; the wrapper substitutes the terse versions, cutting the per-request schema payload ~70-80% while keeping enough to pick the right tool.
- **`tool_scoping.py`** — `scope_agent_tools()` fetches per server and filters via `scoped()`; skips `get_tools()` entirely for servers an agent wants zero tools from (so a down mcp-atlassian can't fail a Security/Performance/Regression build). Each scoped tool is wrapped so its call/result is emitted to the event bus tagged with the owning subagent (subagent-internal MCP calls are invisible to the orchestrator's message walk), tool results fed back to the model are truncated to 4000 chars (they sit in conversation history and are re-sent every turn), and OpenAI-style `anyOf`-null unions are stripped from args schemas (strict tool-call validation rejects them).

**Atlassian connection — confirmed exact launch command** (self-hosted `mcp-atlassian`, chosen over the official Rovo server because it needs a plain API token, no org-admin enablement step):

```bash
uvx mcp-atlassian --transport streamable-http --port 9000
```
Auth via env vars (`JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, plus the Confluence equivalents) passed to that process, not through the MultiServerMCPClient headers.

**Atlassian server-side hardening (both launch paths — `run_atlassian_server.sh` and the compose service):** `READ_ONLY_MODE=true` blocks every write action; `TOOLSETS=all` keeps the full 58-tool set available (mcp-atlassian v0.22+ otherwise defaults to only 6 core toolsets once the default flips); `ENABLED_TOOLS=jira_get_issue,confluence_search,confluence_get_page` is an exact-name allowlist that mcp-atlassian enforces at both `tools/list` and call time (its `_is_tool_authorized`, v0.23.0). No review agent can ever reach the ~38 other Jira tools or ~20 other Confluence tools — not even a read like `jira_search`. This is the server-side half of the "no blanket Atlassian tools" guarantee; the client-side half is each agent's exact `allowed_names` set below (deliberately redundant, same as GitHub). `ALLOW_GLOBAL_CRED_FALLBACK=true` is mcp-atlassian's single-user global-credential fallback gate — it applies to any server-side auth type (our Cloud API tokens included), not just mTLS — and is required since 0.23.0 because our client sends no per-request Atlassian auth headers. Revisit it only if a later phase adds per-user Atlassian auth.

**GitHub connection:** PAT via `Authorization: Bearer` header — simplest headless auth, no GitHub App/org setup required. OAuth is the alternative for a real multi-org deployment later, not needed now. Read-only is enforced twice, deliberately redundant: server-side via the `X-MCP-Readonly`/`X-MCP-Toolsets` headers above, and client-side via each agent's explicit `allowed_names` set below (see Per-Agent Breakdown) — no agent's tool list is ever "all GitHub tools."

---

## Per-Agent Breakdown — Exact Tools and Why

**GitHub tool names are verified and hardcoded in `tool_lists.py`.** They were checked against the live GitHub MCP registry (30 tools, zero write-capable names) before implementation — the exact names used are `pull_request_read`, `get_file_contents`, `list_commits`, `search_code`, `list_code_scanning_alerts`, `get_code_scanning_alert`, `list_dependabot_alerts`, `get_dependabot_alert`, `actions_list`, `actions_get`, `get_job_logs`. Context7's tools are `resolve-library-id` and `query-docs`. If GitHub ever consolidates names again, re-verify with `mcpcurl tools --help` and update `tool_lists.py` — don't guess.

### Compliance
**Role:** does this diff match what was asked (Jira) and follow team standards (Confluence)?

| Tool | Server | Why |
|---|---|---|
| `get_review_context_tool` | CRG | Token-optimized structural summary — the entry point before reasoning about anything else |
| `query_graph_tool` | CRG | Callers/callees/imports/inheritance — structural rules aren't visible in diff text alone |
| `get_architecture_overview_tool` | CRG | Layering/module-boundary checks against the codebase's actual shape |
| `find_large_functions_tool` | CRG | Direct match for "keep functions under N lines" style standards |
| `get_knowledge_gaps_tool` | CRG | Untested public API standards |
| `jira_get_issue` | Atlassian | The ticket itself — its acceptance criteria are the definition of "what was asked" |
| `confluence_search` | Atlassian | Find the standards doc / ADR relevant to this change |
| `confluence_get_page` | Atlassian | Read the actual standards document body |
| `pull_request_read` | GitHub | The actual diff being reviewed — Compliance can't check ticket/standards match against a diff it can't see |
| `get_file_contents` | GitHub | Full file context around a diff hunk, not just the changed lines |
| `list_commits` | GitHub | Commit history on the PR — multiple commits can matter for ticket-scope review |
| `search_code` | GitHub | Locate other usages of a pattern to check consistency with team standards |

### Security
**Role:** does this change introduce a security risk?

| Tool | Server | Why |
|---|---|---|
| `get_impact_radius_tool` | CRG | Risk isn't just the line itself — how far can a vulnerable pattern propagate through callers |
| `get_bridge_nodes_tool` | CRG | A change to a chokepoint is architecturally higher-risk by definition |
| `get_surprising_connections_tool` | CRG | Unexpected coupling is often exactly how an unintended access path gets introduced |
| `detect_changes_tool` | CRG | Quantified risk score, not just "this looks scary" |
| `pull_request_read` | GitHub | The diff itself |
| `get_file_contents` | GitHub | Full file context around a flagged line |
| `list_code_scanning_alerts` | GitHub | Existing CodeQL/code-scanning findings for this repo |
| `get_code_scanning_alert` | GitHub | Detail on a specific alert once flagged |
| `list_dependabot_alerts` | GitHub | Known-vulnerable dependency versions |
| `get_dependabot_alert` | GitHub | Detail on a specific dependency alert |
| `resolve-library-id`, `query-docs` | Context7 | Is this API/library usage now known-insecure or deprecated — **curated to these two read-only docs tools** (was "all Context7 tools"; trimmed to cut prompt noise and selection errors) |

### Performance
**Role:** does this change risk a performance regression?

| Tool | Server | Why |
|---|---|---|
| `list_flows_tool` | CRG | Establishes which execution flows matter most, ranked by criticality |
| `get_flow_tool` | CRG | Detail on a specific flow once a candidate is identified |
| `get_affected_flows_tool` | CRG | Does the diff touch a hot path at all, before spending reasoning effort on it |
| `get_hub_nodes_tool` | CRG | A change to a hub node compounds — called from many places |
| `pull_request_read` | GitHub | The diff itself |
| `get_file_contents` | GitHub | Full file context around a changed hot path |
| `list_commits` | GitHub | Recent commit history on files in the affected flow |
| Context7 tools | Context7 | Current best-practice patterns (e.g. a now-discouraged ORM call shape) |

### Regression
**Role:** what could this change break — blast radius + untested hotspots.

| Tool | Server | Why |
|---|---|---|
| `get_impact_radius_tool` | CRG | Who calls this, and are they at risk of breaking |
| `detect_changes_tool` | CRG | Test-coverage-gap signal: tells Regression this affected area has no safety net |
| `get_affected_flows_tool` | CRG | Behavioral paths the change touches, not just individual functions |
| `traverse_graph_tool` | CRG | Open-ended multi-hop exploration when fixed-shape tools aren't enough |
| `get_knowledge_gaps_tool` | CRG | Untested hotspots — exactly where regressions hide |
| `pull_request_read` | GitHub | The diff itself |
| `get_file_contents` | GitHub | Full file context around the change |
| `actions_list` | GitHub | CI/CD workflow runs for this PR/commit |
| `actions_get` | GitHub | Status of a specific workflow run |
| `get_job_logs` | GitHub | Actual test pass/fail detail, not just the run's overall status |

### Fix Suggestion
**Role:** propose a concrete, grounded fix.

| Tool | Server | Why |
|---|---|---|
| `semantic_search_nodes_tool` | CRG | Find existing patterns elsewhere to base a fix on, instead of inventing a novel approach |
| `refactor_tool` | CRG | Preview a rename/dead-code/fix suggestion |
| `get_docs_section_tool` | CRG | Ground the fix in the repo's own documented conventions |
| `confluence_search` | Atlassian | Find a documented pattern or ADR relevant to the finding |
| `confluence_get_page` | Atlassian | Read the concrete pattern/ADR to cite as justification |
| Context7 tools | Context7 | Verify the fix against the library's *current* API before suggesting it |

**Do not give Fix Suggestion `apply_refactor_tool`.** That tool writes code changes, not just proposes them. Giving an LLM agent the ability to autonomously apply a change violates the safety principle already established for this project (suggestions get validated before surfacing, never auto-applied). If applying a fix is ever automated, it's a separate, explicitly user-triggered action outside this agent's own tool list — not a decision the agent makes for itself.

### Orchestrator / Aggregator
No MCP tools. Orchestrator classifies + routes via the Routing Policy; Aggregator synthesizes structured `AgentFinding`s into one reply. Neither queries the graph or any external service directly.

---

## Incoming Request Schema

`POST /review`'s body was never specified before — this is the gap. Lives in `infrastructure/api/models.py`, **not** `domain/` — this is Layer 2's job (API request/response shapes), not a Domain entity; putting Pydantic models in `domain/` would violate the "zero framework imports" rule the same way an `import fastapi` would.

```python
# infrastructure/api/models.py
from pydantic import BaseModel

class ReviewRequest(BaseModel):
    repo_id: str
    graph_commit_hash: str | None = None   # optional — exactly ONE of this OR branch is required (400 if both/neither)
    branch: str | None = None              # optional — per-branch review (Branch-Aware addendum); see Branch Handling below
    request_type: str        # must match a key in the Routing Policy below; the route 400s on unknown types
    diff_content: str | None = None   # optional — explain_question etc. may not need one
    question: str | None = None       # optional — free-form question; steers any_question (available pool) AND the single-specialist question types (compliance_question / security_question / performance_question / impact_question). Ignored by review (full pipeline) and explain_question.
```

`POST /review` returns `{"review_session_id": <int>, "result": <JSON string of the aggregated AgentOutput>, "timeline": {<agent>: [{"kind": "llm"|"tool", "name": ..., "duration_ms": ...}, ...]}, "timeline_text": <plain-text rendering of the timeline>}` and writes one `ReviewSession` row plus one `AgentExecution` row per routed subagent and one for the aggregator in the same Phase 1 SQLite DB. The `timeline`/`timeline_text` fields are diagnostics: they let a caller see every LLM call and tool call per agent with real durations, without having to parse `logs/review_events.log`.

## Pre-Flight: Graph Readiness + Workspace Path Resolution

Two checks that must both happen before any subagent runs, combined into one use-case. The use-case depends only on two Layer 4 ports; the Layer 2 route is the composition root that wires Phase 1's `GraphReadinessService` and two Layer 5 SQLModel adapters into it:

```python
# domain/review/review_context_ports.py  (Layer 4, plain Protocol — no framework, no SQL)
class RepoWorkspaceQueryPort(Protocol):
    def get_by_repo_id(self, repo_id: str) -> RepoWorkspace | None: ...
    def get_by_repo_id_and_branch(self, repo_id: str, branch: str) -> RepoWorkspace | None: ...
    def repo_is_registered(self, repo_id: str) -> bool: ...

class GraphReadinessPort(Protocol):
    def is_ready(self, repo_id: str, commit_hash: str) -> bool: ...

# application/review_service/prepare_review_context.py  (Layer 3, pure use-case)
class PrepareReviewContextService:
    def __init__(self, workspace_query: RepoWorkspaceQueryPort, readiness: GraphReadinessPort) -> None: ...

    def execute(self, repo_id: str, graph_commit_hash: str, branch: str | None = None) -> str:
        """Returns repo_root (local_path). Raises RepoNotFoundError / GraphNotReadyError.
        ``branch`` selects a per-branch workspace row (Branch-Aware addendum §5);
        None keeps the default-branch (base-clone) row, preserving Phase 1 semantics.
        Pure and side-effect-free — it never triggers a build; the route does that."""
        if not self._workspace_query.repo_is_registered(repo_id):
            raise RepoNotFoundError(repo_id)                       # -> 404
        workspace = self._workspace_query.get_by_repo_id_and_branch(repo_id, branch) \
            if branch is not None else self._workspace_query.get_by_repo_id(repo_id)
        if workspace is None:
            raise GraphNotReadyError(repo_id, graph_commit_hash)   # -> 425
        # The commit-mismatch gate applies ONLY to the branch path (review finding #1):
        # a worktree must be fast-forwarded + rebuilt before its graph is served, so a
        # stale per-branch row is a 425. The plain graph_commit_hash path keeps Phase 1
        # semantics — readiness of the requested commit's graph snapshot is the sole gate,
        # so an OLDER commit whose graph is ready remains servable (it never triggers a
        # rebuild, and there is nothing to rebuild it from; gating it would produce an
        # unrecoverable 425 since the route only rebuilds for the branch path).
        if branch is not None and workspace.last_synced_commit != graph_commit_hash:
            raise GraphNotReadyError(repo_id, graph_commit_hash)   # -> 425
        if not self._readiness.is_ready(repo_id, graph_commit_hash):
            raise GraphNotReadyError(repo_id, graph_commit_hash)   # -> 425
        return workspace.local_path

# infrastructure/api/routes/review.py  (Layer 2 composition root)
_prepare_context = PrepareReviewContextService(
    SQLModelRepoWorkspaceRepository(),                # infra/db/repo_workspace_repository.py
    GraphReadinessService(SQLModelGraphStatusQuery()), # infra/db/graph_status_repository.py
)
# repo_root = _prepare_context.execute(body.repo_id, body.graph_commit_hash, branch=body.branch)
#   RepoNotFoundError   -> HTTPException(404, f"Unknown repo_id: {repo_id}")
#   GraphNotReadyError  -> HTTPException(425, "Graph not ready for this commit yet")
```

**Why this matters, concretely:**
- **`local_path` comes from the DB, never from a guessed or LLM-supplied path** — this is what every subagent's `repo_root` argument to CRG tools is actually resolved from. Nothing constructs a filesystem path from `repo_id` directly.
- **425, not a silent wait or a stale query** — if the graph isn't ready for this exact commit, subagents must not run against a graph that's mid-update or doesn't exist yet.

**Async note:** `GraphReadinessService` and the `RepoWorkspace` lookup are Phase 1 code — synchronous, by Phase 1's own design. Calling a sync DB read directly inside this phase's `async def` route would block the event loop for its duration. For a single fast SQLite read this is a minor, acceptable exception in practice — but if you want to keep the async layer strictly non-blocking, wrap the call: `repo_root = await asyncio.to_thread(_prepare_context.execute, body.repo_id, body.graph_commit_hash)` from the route handler. Either is acceptable; pick one and be consistent, don't mix.

**Implementation note:** the use-case (`PrepareReviewContextService`) is pure Layer 3 — no FastAPI, no SQLModel, no `infrastructure` imports. Its two ports are declared in `domain/review/review_context_ports.py` and implemented by `infrastructure/db/repo_workspace_repository.py` (the `select(RepoWorkspace)...` query the webhook flow uses) and `infrastructure/db/graph_status_repository.py` (a direct `GraphSnapshot` query returning a `GraphBuildStatus` entity). Phase 1 defines `GraphReadinessService` but never instantiates it, so the Layer 2 route composes it with the latter adapter. The route translates the use-case's application-layer exceptions (`RepoNotFoundError` → 404, `GraphNotReadyError` → 425) into HTTP status codes.

---

## Branch Handling (Branch-Aware addendum to Phase 2)

The system reviews **per-branch** code, not just the default branch. This section is the Phase 2 reference; `Branch-Aware Graph Management.md` (§0–§14) is the authoritative spec this was built against. **Trigger model is manual only (§2):** a worktree and its graph are created or updated for **exactly one reason — a user submits `POST /review` for a `(repo_id, branch)` pair.** UI branch selection has no side effect on its own.

### The trigger flow (§5)

`POST /review` with `body.branch` set, in order:
1. **Validate:** exactly one of `graph_commit_hash`/`branch` — both or neither → 400.
2. **Resolve branch → commit** live via GitHub MCP `list_branches` (`infrastructure/mcp_clients/branch_resolution.py`, async Layer 5, `scoped()`-reduced to `{list_branches}`, uses `request.app.state.mcp_client`). Unknown branch → 404 `BranchNotFoundError`; unregistered repo → 404. Non-JSON tool output (e.g. an MCP tool error / rate-limit payload) is guarded — `json.loads` wrapped in `try/except ValueError` → `BranchNotFoundError` (review finding #4) — so it surfaces as a clean 404 instead of an uncaught parse error → 500.
3. **Pre-flight** (`PrepareReviewContextService.execute(repo_id, resolved_commit, branch=branch)`): 404 unregistered; 425 when the per-branch row is missing OR `last_synced_commit != resolved_commit` OR the graph isn't ready. **The commit-mismatch gate is scoped to the branch path only (review finding #1):** the plain `graph_commit_hash` path keeps Phase 1 semantics — the readiness of the requested commit's graph snapshot is its sole gate, so a ready *older* commit is served even when the base clone has moved past it (there is no worktree to rebuild, so gating on the mismatch would produce an unrecoverable 425).
4. **On 425-with-branch:** the route dispatches `EnsureBranchWorktreeService.execute(...)` as a FastAPI `BackgroundTasks` task (the D-11 fix — return a `JSONResponse(425)` with `response.background = background_tasks` set; a `raise HTTPException` silently drops the queued task), then returns 425 immediately. The background task creates/updates the worktree and builds its graph; a later `POST /review` for the same (repo, branch) at the resolved commit then passes pre-flight.

### When a graph actually updates (the exact rule)

- **Default branch (base clone):** auto-updates on every webhook push via `SyncOnWebhookService` — `process_webhook` (`webhooks.py`) is branch-aware and only acts when `base.branch == branch` (the default-branch row). Unchanged from Phase 1.
- **Non-default (worktree) branch:** updates **only when a user submits `POST /review` for that branch**, and only if the branch's remote tip has moved past what was last built (the pre-flight 425 triggers `EnsureBranchWorktreeService`). A push to the branch is a **webhook no-op** — it does not update that branch's graph. Because `branch_resolution` resolves the *current remote tip*, the next review of the branch detects any advance and triggers the incremental update. If the branch is already current, submitting a review reuses the existing graph (no rebuild).

### Worktree lifecycle (§3)

`EnsureBranchWorktreeService` (`application/repo_ingestion_service/ensure_branch_worktree.py`, sync, injected `RepoSourcePort` + `GraphBuilderPort` + `WorkspaceStore`):
- **No row yet** (branch never requested) → `create_worktree` + full `build()` (`full_rebuild=True`).
- **Row exists but tip advanced** → `update_worktree` + incremental `update(base=old last_synced_commit)`; if that fails (e.g. force-push made the base unreachable → CRG returns non-ready), **fall back to a full `build()`**.
- Records `last_synced_commit` + a `GraphSnapshot`; releases the per-branch lock in a `finally`.

`GitRepoSource.create_worktree`/`update_worktree` (`git_repo_source.py`): a Phase 1 clone is shallow/depth-1 (single-branch), so `create_worktree` first runs `git fetch origin <branch>:<branch>` into the base clone, then `git worktree add <path> <branch>`; `update_worktree` runs `git fetch origin <branch>:refs/remotes/origin/<branch>` then `git reset --hard origin/<branch>` and returns the new HEAD sha.

### Worktree paths (§12)

Siblings of the base clone, still under `WORKSPACE_ROOT` (visible to the CRG server container): base clone at `{root}/{safe_id}`, worktree at `{root}/{safe_id}__{safe_branch}` (`infrastructure/workspace/workspace_path_resolver.py` → `resolve_workspace_path`/`resolve_worktree_path`). No `CRG_DATA_DIR` override — worktree isolation is by filesystem path, verified against CRG docs before implementation (§12 "Not set" holds).

### Locks (§8)

`acquire_workspace_lock(workspace_root, repo_id, branch=None)` — branch scope moved to `(repo_id, branch)`; a branch lock file is `.{safe_id}_{safe_branch}.lock`; `branch=None` keeps the Phase 1 default key `.{safe_id}.lock`. `try_acquire_lock` (`timeout=0`) is a non-blocking probe the route uses to skip dispatch when another request is already building the branch.

### Webhooks (§6, §9) — now branch-aware

- `process_webhook(repo_id, branch, commit_sha)` is a **no-op** unless the pushed branch equals the default-branch row's branch (`base.branch != branch → return`). Non-default (worktree) branches never auto-sync via webhook.
- `000…0` (branch deletion) is a real **dispatch** to `cleanup_deleted_branch`, not an early return: it runs `git worktree remove` + `git worktree prune` in the base clone, deletes the per-branch `RepoWorkspace` row, and **leaves `GraphSnapshot` rows** (they're commit-keyed and may back past audit rows). PR-closed is NOT a trigger.
- New read-only `GET /repos/{repo_id:path}/branches` proxies all remote branches (404 for unregistered repos). `{repo_id:path}` is required because `repo_id` is `owner/repo` (contains a slash).

### Schema migration (§7)

`RepoWorkspace` is now one row **per (repo_id, branch)**: composite `UNIQUE(repo_id, branch)` + a non-unique index on `repo_id`; `branch` and `last_requested_at` columns added. `db/engine.py` runs a real **4-step rebuild** (create `repoworkspace_new` → INSERT backfill → DROP → RENAME), guarded on `branch` column presence, transactional, idempotent — **not** a guarded `ALTER TABLE`. Backfill is deterministic via `detect_branch` (`git branch --show-current` → `git symbolic-ref refs/remotes/origin/HEAD` fallback), raises rather than guessing; `last_requested_at` derived from `updated_at`. **Stale-row skip (review finding #3):** a row whose `local_path` directory no longer exists is treated as a stale/orphaned entry (e.g. a worktree removed out-of-band) — it is **skipped and logged** so a single stale row cannot brick application startup; a live clone whose branch genuinely cannot be determined still raises loudly. `graphsnapshot` unchanged; no new tables. `get_by_repo_id` is scoped to the default-branch row (`id.asc()`); `repo_is_registered` + `get_by_repo_id_and_branch` added to the repository.

### Worktree-aware eviction (§11)

`WorkspaceEvictionService` orders rows by `last_requested_at` (fallback `updated_at`), and for a worktree uses `git worktree remove --force` + `git worktree prune` (via the base clone resolved as the sibling `{root}/{sanitize_repo_id(repo_id)}`) so the base clone's `.git/worktrees` metadata is cleaned, falling back to `shutil.rmtree` for a base clone or when the base is missing. (E.15 fix: the base-clone path is resolved *deterministically* as that sibling — an earlier walk-up attempt could never reach the sibling base and caused `rmtree` to leave stale worktree metadata.) Existing `max_gb=10.0` default unchanged (no invented thresholds); wired to run once off the event loop in the lifespan. The recency signal is refreshed on the `POST /review` success path for branch rows via `_touch_recency` (`review.py`): a best-effort `touch_requested_at` wrapped in `try/except` (log + continue) so a bookkeeping failure (SQLite locked past `busy_timeout`, I/O error) can never abort the review before its audit rows are written — review finding #2.

### Frontend-Phase Notes (recorded now for the React frontend — do not build here)

These three points are the frontend contract for the branch-switch UI, captured during the Branch-Aware work so they are not reverse-engineered later:

- **Required — the branch-switch dropdown must be populated from `GET /repos/{repo_id:path}/branches` (the GitHub-backed proxy), NOT from `RepoWorkspace`.** That endpoint returns *every remote branch* (`[{name, sha, protected}]`); `RepoWorkspace` only ever holds the branches that have actually been reviewed (the default-branch row after `POST /repos`, plus one row per branch a review was requested on). A dropdown built from `RepoWorkspace` would be near-empty right after repo registration, which is why the endpoint — not the table — is the source of truth. First-time click on an unbuilt branch → 425 → background worktree build → poll `POST /review` until 200.
- **Required verification (before the frontend phase) — confirm whether the GitHub MCP `list_branches` tool paginates.** If it caps the result set (e.g. ~30 branches), a large repo would silently show a partial dropdown. Verify the live tool name with `mcpcurl tools --help` (AGENTS.md standing rule) and, if pagination is confirmed, handle it inside `list_repo_branches` (`branch_resolution.py`) before the UI depends on completeness.
- **Optional — add a readiness probe so the UI does not poll `POST /review`.** Today the only way to distinguish "graph still building" (425) from "done" (200) is to re-submit the full review payload, which re-runs the pre-flight and could re-queue work. A lightweight read-only probe — e.g. `GET /api/v1/repos/{repo_id}/branches/{branch}/readiness` → `{"ready": true, "commit": ...}` or `{"ready": false}` — would let the UI poll cheaply without side effects.

### Documented deviations (in `OPENCODE.md`)

- **D-8** — `RepoSourcePort` has three new methods (`create_worktree`, `update_worktree`, `current_branch`); spec §3 names two — `current_branch` supports the migration backfill + `clone_repository` (plain read, no behavior risk).
- **D-9** — route wires a module-level `EnsureBranchWorktreeService` instance + `BackgroundTasks` instead of a spec-named module fn; functionally equivalent composition root.
- **D-10** — branch identity for a non-default worktree row is the requested branch string (worktree checkout fixes the commit); `last_synced_commit` records the built commit.
- **D-11** — FastAPI drops `BackgroundTasks` on `raise HTTPException`; fixed via `JSONResponse(425)` + `response.background`. Verified against installed FastAPI source and live.

---

## Agent Contracts

```python
# domain/entities/agent_finding.py
from dataclasses import dataclass, field

@dataclass
class AgentInput:
    repo_id: str
    graph_commit_hash: str
    request_type: str
    diff_content: str | None = None
    repo_root: str = ""          # DB-resolved local_path from PrepareReviewContextService
    question: str | None = None  # free-form question for any_question; also forwarded for compliance/security/performance/impact question types

@dataclass
class AgentFinding:
    severity: str          # "info" | "warning" | "critical"
    confidence: float      # 0.0-1.0
    title: str
    description: str
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""

@dataclass
class AgentOutput:
    agent_name: str
    findings: list[AgentFinding] = field(default_factory=list)

@dataclass
class ReviewResult:
    """Outcome of one review run: the aggregated reply plus one output per
    routed subagent (the audit trail needs both)."""
    aggregated: AgentOutput
    per_agent: list[AgentOutput] = field(default_factory=list)
```

**Confidence threshold:** a finding below 0.6 is low-confidence. Since there's no Context Agent yet to fetch more history, a low-confidence finding this phase is just surfaced as-is with its score visible — do not build any "fetch more context" fallback behavior; that's future-phase territory.

**Serialization for `AgentExecution.result`:** `AgentOutput`/`AgentFinding` are plain dataclasses — `json.dumps()` cannot serialize them directly, it raises `TypeError`. Convert first:

```python
import dataclasses, json

result_json = json.dumps(dataclasses.asdict(agent_output))
```

## Routing Policy

Implemented in `domain/review/routing_policy.py`. `agents_for_request(request_type)` returns a non-empty list (dispatch subagents), `[]` for a *valid* type the orchestrator answers directly, or `None` for an *unknown* type — the route converts `None` to a 400.

```yaml
review:
  agents: [compliance, security, performance, regression]

security_question:
  agents: [security]

compliance_question:
  agents: [compliance]

performance_question:
  agents: [performance]

impact_question:
  agents: [regression]

explain_question:
  agents: []   # orchestrator answers directly

any_question:   # user-approved extension (supervisor-demo requirement)
  agents: [compliance, security, performance, regression]   # AVAILABLE POOL, not a required set
```

`performance` must be present in the `review` entry — it was missing in an earlier draft of this policy; do not reproduce that omission.

**`any_question` (user-approved extension):** the four specialists form an *available pool*, not a forced set. The orchestrator reads the free-form `question` and delegates to the specialist(s) whose domain it concerns — one, several, or none (answering directly when nothing matches). The user message spells out the pool + the question and lets the orchestrator choose; every other request type spells out a REQUIRED list the orchestrator MUST delegate to.

## Event Schema (log only, no UI consumer yet)

```
{ type: "thinking", agent: "compliance", content: "..." }
{ type: "tool_call", agent: "compliance", tool: "query_graph_tool", input: {...} }
{ type: "tool_result", agent: "compliance", tool: "query_graph_tool", output: {...} }
{ type: "llm_call", agent: "compliance", model: "...", duration_ms: 2796 }
{ type: "final", content: "..." }
```

**Implemented extensions to the schema:** entries are JSON lines written to stdout (via `logging`, `EVENT <json>`) and appended to `logs/review_events.log` (file writes offloaded with `asyncio.to_thread`). Every event carries `ts` (epoch ms) and, where a duration is measured, `duration_ms`. Beyond the four spec events, the capture middleware adds `tool_call_attempt` (a tool call the model *emitted* — proving a `tool_call_attempt` with no matching `tool_call` means the runtime rejected it) and `invalid_tool_call` (a rejected/malformed call), and `llm_call` (each model invocation, per agent, with model id and real duration). Subagent-internal MCP calls are tagged with their owning agent via the `tool_scoping` wrapper. Path note: the log path is CWD-relative (`logs/review_events.log`) and there is no `launch_uvicorn.cmd` in the repo — the app is launched directly with `uvicorn`/`python -m uvicorn`, and in the current setup that happens from `backend/src/code_review_agent/`, so the active log is `backend/src/code_review_agent/logs/review_events.log`.

---

## Folder Architecture (additive to Phase 1 — nothing below is deleted, everything from Phase 1 stays)

```
backend/src/code_review_agent/
│
├── domain/                                    # existing from Phase 1, extended
│   ├── entities/
│   │   ├── repo_workspace.py                  # (Phase 1, EXTENDED — adds branch, last_requested_at)
│   │   ├── graph_build_status.py              # (Phase 1, unchanged)
│   │   └── agent_finding.py                   # NEW — AgentInput, AgentFinding, AgentOutput, ReviewResult
│   ├── repo/
│   │   └── repo_source_port.py                # (Phase 1, EXTENDED — create_worktree, update_worktree, current_branch; D-8)
│   ├── graph/
│   │   └── graph_builder_port.py              # (Phase 1, unchanged)
│   └── review/                                 # NEW
│       ├── review_context_ports.py              # NEW — RepoWorkspaceQueryPort + GraphReadinessPort (Protocols)
│       ├── review_orchestrator_port.py         # NEW — async def run_review(...)
│       └── routing_policy.py                   # NEW — plain Python/YAML-loader, no framework import
│
├── application/                                # existing from Phase 1, extended
│   ├── repo_ingestion_service/                 # (Phase 1, EXTENDED — ensure_branch_worktree.py added)
│   │   └── ensure_branch_worktree.py           # NEW — EnsureBranchWorktreeService: create/update worktree + build/update graph (§5)
│   ├── graph_build_service/                    # (Phase 1, unchanged)
│   └── review_service/                         # NEW
│       ├── prepare_review_context.py           # NEW — pure use-case (no framework/SQL): readiness check (425) + local_path resolution from DB via injected ports; branch kwarg added
│       ├── errors.py                           # NEW — RepoNotFoundError, GraphNotReadyError, UnknownRequestTypeError (app-layer, no FastAPI)
│       └── run_review.py                       # routes via routing_policy -> invokes ReviewOrchestratorPort
│
├── infrastructure/                             # existing from Phase 1, extended
│   ├── config.py                               # (Phase 1, extended with review_model, review_max_tokens, review_timeout, github_pat, context7_api_key, atlassian settings; extra="ignore")
│   ├── repo_source/                            # (Phase 1, EXTENDED — create_worktree/update_worktree in git_repo_source.py)
│   ├── graph_builder/                          # (Phase 1, unchanged)
│   ├── graph_service/                          # (Phase 1, unchanged)
│   ├── workspace/
│   │   ├── workspace_path_resolver.py          # NEW — resolve_workspace_path + resolve_worktree_path (§12)
│   │   ├── workspace_lock.py                   # (Phase 1, EXTENDED — branch=None param, per-branch lock key, try_acquire_lock)
│   │   └── workspace_eviction_service.py       # (Phase 1, EXTENDED — worktree-aware LRU, git worktree remove; §11)
│   ├── db/
│   │   ├── models.py                           # (Phase 1 tables EXTENDED — RepoWorkspace per-branch) + NEW ReviewSession, AgentExecution
│   │   ├── engine.py                           # (Phase 1, EXTENDED — WAL pragma + RepoWorkspace 4-step rebuild migration)
│   │   ├── repo_workspace_repository.py        # NEW — SQLModelRepoWorkspaceRepository, implements RepoWorkspaceQueryPort (get_by_repo_id_and_branch, repo_is_registered)
│   │   └── graph_status_repository.py          # NEW — SQLModelGraphStatusQuery, feeds GraphReadinessService
│   ├── mcp_clients/                            # NEW
│   │   ├── mcp_client_factory.py               # builds the shared MultiServerMCPClient
│   │   └── branch_resolution.py                # NEW — async list_branches proxy (scoped to {list_branches}) + resolve_branch_to_commit (§4)
│   ├── agents_runtime/                         # NEW
│   │   ├── orchestrator_runtime.py             # one create_deep_agent root (orchestrator + aggregator); tolerant report parsing + bounded retry
│   │   ├── harness_profile.py                  # safety HarnessProfile: strips 8 built-in tools, disables general-purpose subagent
│   │   ├── capture.py                          # CaptureStore + SubagentCaptureMiddleware: real duration_ms + model-call events
│   │   ├── report_schema.py                    # FindingItem/SubagentReport (Pydantic) — the deepagents response_format
│   │   ├── tool_lists.py                       # AGENT_TOOL_PLAN: single source of per-agent tool names
│   │   ├── tool_descriptions.py                # one-line description overrides (~70-80% token cut)
│   │   ├── tool_scoping.py                     # scope_agent_tools + per-agent event-wrapped tools + 4k result truncation
│   │   ├── prompts/
│   │   │   ├── orchestrator.md
│   │   │   ├── compliance.md
│   │   │   ├── security.md
│   │   │   ├── performance.md
│   │   │   ├── regression.md
│   │   │   ├── fix_suggestion.md
│   │   │   └── aggregator.md
│   │   └── subagents/
│   │       ├── compliance_runtime.py           # build_*_spec(mcp_client, store) -> subagent dict + capture middleware
│   │       ├── security_runtime.py
│   │       ├── performance_runtime.py
│   │       ├── regression_runtime.py
│   │       └── fix_suggestion_runtime.py
│   ├── event_bus/                              # NEW
│   │   └── log_event_bus.py                    # logs event schema to stdout/file, no streaming yet
│   └── api/
│       ├── models.py                           # NEW — ReviewRequest (Pydantic), Layer 2, not domain
│       └── routes/
│           ├── webhooks.py                     # (Phase 1, EXTENDED — branch-aware: default-branch-only sync, 000...0 cleanup, GET /repos/{repo_id}/branches)
│           └── review.py                       # NEW — POST /review; runs the pre-flight service (404/425) first, then dispatches agents; branch path dispatches EnsureBranchWorktreeService (D-11 JSONResponse 425)
│
├── scripts/
│   ├── run_crg_server.sh                       # (Phase 1, unchanged)
│   └── run_atlassian_server.sh                 # NEW — `uvx mcp-atlassian --transport streamable-http --port 9000`
│
└── docker-compose.yaml                         # extended: add the mcp-atlassian service alongside existing volumes
```

Additive wiring beyond the tree: `main.py`'s existing lifespan now also runs a CRG connectivity check (`CRGServerManager.ensure_connected(timeout=10)` — a check, not a launcher) and builds the shared client once (`app.state.mcp_client = build_mcp_client()`), runs the worktree-aware eviction once off the event loop (§11), and the review router is included under `/api/v1`. All strictly additive — no Phase 1 logic was modified. (The Phase 1 do-not-modify allowance is `config.py`, `db/models.py`, `db/engine.py`; the `main.py` wiring is this phase's documented, additive exception.)

**New DB tables** — same SQLite file as Phase 1, same `SQLModel` pattern. Do not stand up Postgres yet.

### SQLite Note — Read Before Touching `db/engine.py`

SQLite allows only one writer for the whole file at a time. Phase 1's tables (`RepoWorkspace`, `GraphSnapshot`) write rarely enough that this was never a real constraint. This phase adds `AgentExecution` — one row per subagent per review, several writes in quick succession every time a review runs — which is a meaningfully higher write frequency than Phase 1 had.

This is not yet a reason to migrate to Postgres. It **is** a reason to apply a cheap, necessary mitigation now, since `db/engine.py` is being touched in this phase anyway:

```python
from sqlmodel import create_engine, event

engine = create_engine("sqlite:///data/phase1_metadata.db")

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()
```

`journal_mode=WAL` lets reads proceed during a write; `busy_timeout` makes a second concurrent writer wait and retry instead of immediately raising `SQLITE_BUSY`. This does not remove SQLite's single-writer ceiling — it raises it enough for this phase's actual load.

**The real migration trigger, for whichever phase hits it first — not necessarily the conversation-memory phase specifically:** either (a) conversation memory is built (guaranteed high write frequency per turn), or (b) enough repos have concurrent real-world commit/review activity that `GraphSnapshot`/`AgentExecution` writes start colliding across *different* repos (the per-repo `FileLock` from Phase 1 does not prevent this — it only serializes writes *within* one repo, not across repos). Whichever condition arrives first is the actual trigger; this is a project-level decision already recorded in `ARCHITECTURE.md` Section 6, not something to re-decide per phase.

**Table creation — already wired by Phase 1, do not re-add it.** An earlier draft of this note wrongly claimed Phase 1 never specified table creation. In fact, Phase 1 already does this: `db/engine.py` defines `init_db()`, which calls `SQLModel.metadata.create_all(engine)`, and `main.py`'s lifespan invokes `init_db()` at startup. Because `init_db()` imports `infrastructure.db.models` wholesale, Phase 2's new tables are created automatically once `ReviewSession`/`AgentExecution` are added to `db/models.py` — **no new startup wiring is required in this phase.** If the tables ever need to be created independently (e.g. in a script or test), this is the equivalent call:

```python
from sqlmodel import SQLModel

# only needed outside the normal app startup path — main.py's lifespan already runs it
SQLModel.metadata.create_all(engine)
```

`create_all` is safe to run at every startup — it only creates tables that don't already exist, so it won't touch Phase 1's existing data.

```python
from datetime import datetime, timezone

class ReviewSession(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    repo_id: str
    graph_commit_hash: str
    request_type: str
    model: str | None = None    # settings.review_model (the configured spec) — written directly by the route, not captured
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AgentExecution(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    review_session_id: int = Field(foreign_key="reviewsession.id")
    agent_name: str
    duration_ms: int
    confidence: float | None = None
    model: str | None = None    # canonical_model_label(capture) — the model that actually produced this agent's output, else settings.review_model
    result: str            # JSON-serialized via dataclasses.asdict() — see Agent Contracts above
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**Migration note (added in the observability hardening):** `model` was added to both tables after the phase shipped. `db/engine.py` runs a guarded ALTER (adds missing columns only) in `init_db()` *after* `create_all` (which only creates missing tables, never adds columns to existing ones), so existing SQLite DBs upgrade in place and fresh ones are created with the columns via `create_all`. The `model` column is populated via `canonical_model_label` (in `capture.py`): when the captured model instance matches `settings.review_model` (per `model_matches_spec`, which normalizes provider spelling/case), it returns the canonical full spec verbatim, so `AgentExecution.model` agrees with `ReviewSession.model`; otherwise it falls back to the provider-native identifier (e.g. `nvidia/nemotron-...`) so future per-agent models still get a best-effort label.

**Same fix applies to Phase 1's `RepoWorkspace`/`GraphSnapshot`/`GraphBuildStatus`** — they use the same deprecated `datetime.utcnow()` pattern. Not fixed here since it's outside this phase's scope, but worth doing before mixed naive/aware timestamps across tables in the same DB cause a real comparison bug — flag this in `OPENCODE.md` as a cross-phase cleanup item rather than leaving it unrecorded.

**Exception boundary — required, not optional.** If an LLM call fails or an MCP tool call times out mid-review, an unhandled exception must not skip the audit trail. Implemented in `infrastructure/api/routes/review.py`: the orchestration call is wrapped so a failure still writes an `AgentExecution` row (`agent_name="orchestrator"`, `result` = `{"status": "error", "error": <str>}` — there is no separate `status`/`error` column) before the route returns a 500:

```python
try:
    outcome = await run_review(review_input, orchestrator)
except HTTPException:
    raise
except Exception as exc:
    await asyncio.to_thread(_record_error_execution, session_id, exc)
    raise HTTPException(status_code=500, detail="Review failed") from exc
```

`HTTPException`s (e.g. the 400 for an unknown request_type) pass through untouched. The bounded retry inside `orchestrator_runtime._run_with_retry` runs *before* this boundary, so only genuinely unrecoverable failures reach the error row. `run_review` (Application layer) resolves the routed agent list and 400s on unknown types, making the route's pre-check a defensive double-check.

---

## Documentation Links

| Tool | Repository | Docs |
|---|---|---|
| deepagents | `github.com/langchain-ai/deepagents` | `docs.langchain.com/oss/python/deepagents/subagents` |
| langchain-mcp-adapters | `github.com/langchain-ai/langchain-mcp-adapters` | repo README + `_autodocs/` |
| CRG (code-review-graph) | `github.com/tirth8205/code-review-graph` | `code-review-graph.com` |
| GitHub MCP | `github.com/github/github-mcp-server` | — |
| mcp-atlassian | `github.com/sooperset/mcp-atlassian` | `docs/http-transport.mdx` in the repo |
| Context7 | `github.com/upstash/context7` | `context7.com` |

---

## Definition of Done for This Phase

Items below are marked against the *implemented* state (verified in code and live E2E; evidence in `OPENCODE.md`).

- [x] All 7 agents constructed via `create_deep_agent`: the root agent is the Orchestrator+Aggregator (classify/synthesize phases, `system_prompt` = `orchestrator.md` + `aggregator.md`), and the 5 specialists are registered as plain dict literals in `subagents` via per-agent `build_*_spec()` builders. `response_format=SubagentReport` is set on the root and propagates to every subagent. For an empty routed set (`explain_question`) `subagents=None` — no subagents constructed.
- [x] Each subagent's `tools` list is built by `scope_agent_tools` filtering `MultiServerMCPClient.get_tools()` output to exactly the names in `AGENT_TOOL_PLAN` — no agent has a tool outside its assigned set. (Security's Context7 grant is curated to `{resolve-library-id, query-docs}`; Compliance and Regression take zero Context7 tools; Performance and Fix Suggestion take all Context7 tools.)
- [x] Fix Suggestion has `refactor_tool` but explicitly does NOT have `apply_refactor_tool`.
- [x] The safety `HarnessProfile` strips all 8 built-in tools (`ls`/`read_file`/`write_file`/`edit_file`/`delete`/`glob`/`grep`/`execute`) and disables the general-purpose subagent from every stack — registered under every key deepagents resolves (raw spec + resolved `provider:identifier`).
- [x] GitHub MCP client config includes `"X-MCP-Readonly": "true"` and a scoped `"X-MCP-Toolsets"` header — review agents never get a blanket "all GitHub tools" grant, server-side or client-side.
- [x] `mcp-atlassian` is hardened server-side in both launch paths (script + compose) with `READ_ONLY_MODE=true`, `TOOLSETS=all`, `ALLOW_GLOBAL_CRED_FALLBACK=true`, and `ENABLED_TOOLS=jira_get_issue,confluence_search,confluence_get_page`; client-side Compliance is scoped to exactly `{jira_get_issue, confluence_search, confluence_get_page}` while Fix Suggestion is scoped to exactly `{confluence_search, confluence_get_page}` — no agent gets a blanket "all Jira/all Confluence" grant, server-side or client-side.
- [x] Each GitHub-using agent's `allowed_names` set was checked against the live GitHub MCP tool registry (e.g. via `mcpcurl tools --help`) before implementation, not copied from this doc unverified — verified names recorded in `tool_lists.py`.
- [x] Routing Policy includes `performance` in the `review` entry, the single-specialist types `security_question`/`compliance_question`/`performance_question`/`impact_question` (one specialist each), `explain_question` (direct answer), and the user-approved `any_question` extension (available-pool semantics; unknown request types → `None` → 400).
- [x] `POST /review` validates its body against `ReviewRequest` (Pydantic, in `infrastructure/api/models.py` — not `domain/`), including the optional `question` field.
- [x] `POST /review` runs the pre-flight service (`PrepareReviewContextService.execute`) before dispatching any agent: returns 404 for an unknown `repo_id`, returns 425 if the graph isn't ready for `graph_commit_hash` — verified by testing both failure cases, not just the happy path.
- [x] Every subagent's `repo_root`/CRG tool calls use the `local_path` resolved from `RepoWorkspace` via the pre-flight service — never a guessed or independently-constructed filesystem path. The orchestrator's user message hands every `task` call BOTH `owner`/`repo` (GitHub tools) AND `repo_root` (CRG tools).
- [x] `POST /review` runs orchestrator → subagents (per routing policy) → aggregator, returns `{"review_session_id": <int>, "result": <aggregated AgentOutput JSON>, "timeline": <per-agent llm/tool call log>, "timeline_text": <plain-text rendering>}`.
- [x] `MultiServerMCPClient` is constructed once at FastAPI startup (lifespan), not per-request.
- [x] Phase 2's new tables (`ReviewSession`, `AgentExecution`) actually exist at runtime — satisfied by Phase 1's existing `init_db()`/`create_all` wiring once they were added to `db/models.py`, not by new startup code.
- [x] A failed review still writes an `AgentExecution` row before returning a 500 — verified by forcing a failure (e.g. an invalid MCP URL) and checking the DB, not just reading the code.
- [x] `ReviewSession` and `AgentExecution` rows are written per review, in the same SQLite DB as Phase 1, using timezone-aware (`datetime.now(timezone.utc)`) timestamps. (SQLite round-trip stores naive wall time — cross-phase cleanup tracked in `OPENCODE.md`.)
- [x] `AgentExecution.result` is populated via `json.dumps(dataclasses.asdict(agent_output))`, not a raw `json.dumps(agent_output)` call; per-agent rows carry real `duration_ms` via the capture middleware, and the aggregator row carries the whole-run wall time.
- [x] `review_model` is read from `settings`, has no hardcoded default anywhere in code, and is set via the `REVIEW_MODEL` env var. `review_max_tokens`/`review_timeout` are likewise env-configurable and forwarded through a `ProviderProfile`.
- [x] `tool_name_prefix` is left at its default (`False`) on `MultiServerMCPClient` — no prefix-stripping logic was added to `scoped()`.
- [x] `db/engine.py` sets `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` on connection — required this phase due to `AgentExecution`'s higher write frequency, not optional.
- [x] Event schema entries are logged (stdout + `logs/review_events.log`) for thinking/tool_call/tool_result/final plus the extended `tool_call_attempt`/`invalid_tool_call`/`llm_call` — no UI required.
- [x] `mcp-atlassian` runs via `uvx mcp-atlassian --transport streamable-http --port 9000`, not the official Rovo server.
- [x] Domain layer has zero imports of `deepagents`, `langchain_mcp_adapters`, `pydantic`, or `fastapi`.
- [x] **Branch Handling (Branch-Aware addendum):** `POST /review` accepts exactly one of `graph_commit_hash`/`branch` (400 on both/neither), resolves an unknown `branch` to 404 `BranchNotFoundError`, returns 425 on an unready per-branch graph, and dispatches `EnsureBranchWorktreeService` via `BackgroundTasks` using the D-11 `JSONResponse(425)` + `response.background` fix (a `raise HTTPException` drops the queued build). Commit-mismatch gate scoped to the branch path only (fix #1 — the plain hash path keeps Phase 1 readiness-only semantics so a ready older commit stays servable). Verified live end to end (see `OPENCODE.md`).
- [x] **Worktree lifecycle (§3):** `EnsureBranchWorktreeService` creates the worktree (fetch-then-`git worktree add` for the shallow-clone refspec) with a full `build()` on first request, and fast-forwards via `update_worktree` (fetch + `reset --hard origin/<branch>`) with an incremental `update(base=last_synced_commit)` on later requests, falling back to a full rebuild on force-push base-unreachable; records `last_synced_commit` + `GraphSnapshot` and releases the per-branch lock in a `finally`.
- [x] **Webhooks branch-aware (§6/§9):** `process_webhook` is a no-op for non-default (worktree) branch pushes (only the default-branch row syncs); `000…0` is a real dispatch to `cleanup_deleted_branch` (`git worktree remove` + `prune` + row delete, `GraphSnapshot` left intact, no `pull_request` trigger); read-only `GET /repos/{repo_id:path}/branches` proxies all remote branches (404 unregistered).
- [x] **Schema migration (§7):** `RepoWorkspace` is per-`(repo_id, branch)` with composite `UNIQUE(repo_id, branch)` + non-unique `repo_id` index, migrated via a real 4-step rebuild (create/insert/drop/rename), guarded on `branch` column presence, transactional and idempotent — not a guarded `ALTER TABLE`; branch backfill is deterministic (`detect_branch`) and raises rather than guessing. Stale rows whose `local_path` directory no longer exists are skipped + logged (fix #3 — a single orphaned row cannot brick startup). Migration verified against the real dev DB.
- [x] **Worktree-aware eviction (§11):** `WorkspaceEvictionService` orders by `last_requested_at` (fallback `updated_at`), resolves the base clone as the sibling `{root}/{sanitize_repo_id(repo_id)}`, and uses `git worktree remove --force` + `prune` for worktrees (falling back to `rmtree` for base clones), `max_gb=10.0` unchanged; wired to run off the event loop in the lifespan. Recency refreshed best-effort on the `POST /review` success path via `_touch_recency` (fix #2 — a bookkeeping failure never aborts the review). Covered by focused unit tests.
- [x] Nothing from Phase 1's folder tree was deleted; Phase 1 files were only extended where the addendum allows (`config.py`, `db/models.py`, `db/engine.py`) plus the branch-aware additions (`repo_source_port.py`/`git_repo_source.py`, `workspace_lock.py`, `workspace_eviction_service.py`, `webhooks.py`) and the strictly-additive `main.py` wiring (review-router include, `app.state.mcp_client`, CRG connectivity check, startup eviction).
- [x] No LangMem, no Context Agent, no conversation persistence tables, no frontend, no streaming.
- [x] **Phase 3 sign-off still pending** — reviewer final pass was 29/30; the single minor FAIL (Compliance's Context7 grant) is FIXED. The Branch-Aware addendum's own review (D-8/D-9/D-10/D-11 + one eviction defect E.15) is resolved — see `OPENCODE.md`.
