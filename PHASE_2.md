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

**`config.py` addition:** `review_model: str` with **no default value** — force it via env var (`REVIEW_MODEL=<provider>:<model>`). It is the single model spec for the whole multi-agent system. deepagents resolves it via langchain's `init_chat_model`, which dispatches by provider prefix (`groq:`, `openrouter:`, `google_genai:`, `openai:`, `anthropic:`, `deepseek:`, `ollama:`, ...), so switching providers is a config + package + API-key change, never a code change. Do not hardcode any specific dated model snapshot in code; that just relocates the staleness problem instead of removing it. The provider's langchain integration package (see `requirements.txt`) and its API key env var (e.g. `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_HOST`) must be present — only the one matching `REVIEW_MODEL` is required.

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

**Atlassian connection — confirmed exact launch command** (self-hosted `mcp-atlassian`, chosen over the official Rovo server because it needs a plain API token, no org-admin enablement step):

```bash
uvx mcp-atlassian --transport streamable-http --port 9000
```
Auth via env vars (`JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, plus the Confluence equivalents) passed to that process, not through the MultiServerMCPClient headers.

**Atlassian server-side hardening (both launch paths — `run_atlassian_server.sh` and the compose service):** `READ_ONLY_MODE=true` blocks every write action; `ENABLED_TOOLS=jira_get_issue,confluence_search,confluence_get_page` is an exact-name allowlist that mcp-atlassian enforces at both `tools/list` and call time (its `_is_tool_authorized`, v0.23.0). No review agent can ever reach the ~38 other Jira tools or ~20 other Confluence tools — not even a read like `jira_search`. This is the server-side half of the "no blanket Atlassian tools" guarantee; the client-side half is each agent's exact `allowed_names` set below (deliberately redundant, same as GitHub). `ALLOW_GLOBAL_CRED_FALLBACK=true` is mcp-atlassian's single-user global-credential fallback gate — it applies to any server-side auth type (our Cloud API tokens included), not just mTLS — and is required since 0.23.0 because our client sends no per-request Atlassian auth headers. Revisit it only if a later phase adds per-user Atlassian auth.

**GitHub connection:** PAT via `Authorization: Bearer` header — simplest headless auth, no GitHub App/org setup required. OAuth is the alternative for a real multi-org deployment later, not needed now. Read-only is enforced twice, deliberately redundant: server-side via the `X-MCP-Readonly`/`X-MCP-Toolsets` headers above, and client-side via each agent's explicit `allowed_names` set below (see Per-Agent Breakdown) — no agent's tool list is ever "all GitHub tools."

---

## Per-Agent Breakdown — Exact Tools and Why

**GitHub tool names below must be re-verified against the live server before implementation.** GitHub's MCP tool registry has been consolidating and renaming tools (e.g. individual `create_issue`/`update_issue`-style tools merging into a unified `issue_write`, with newer granular feature-flagged variants alongside them). Confirm exact current names via `mcpcurl tools --help` or the server's own tool list before hardcoding `allowed_names` — don't carry these names forward from this doc unverified.

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
| Context7 tools | Context7 | Is this API/library usage now known-insecure or deprecated |

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
    graph_commit_hash: str
    request_type: str        # must match a key in the Routing Policy below
    diff_content: str | None = None   # optional — explain_question etc. may not need one
```

## Pre-Flight: Graph Readiness + Workspace Path Resolution

Two checks that must both happen before any subagent runs, combined into one step since they're both DB lookups against Phase 1's tables:

```python
# application/review_service/prepare_review_context.py
import asyncio
from fastapi import HTTPException

def prepare_review_context(repo_id: str, graph_commit_hash: str) -> str:
    """Returns repo_root (local_path). Raises HTTPException if not ready."""
    workspace = get_repo_workspace(repo_id)  # query RepoWorkspace — 404 if repo_id unknown
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")

    if not graph_readiness_service.is_ready(repo_id, graph_commit_hash):  # Phase 1's service, sync
        raise HTTPException(status_code=425, detail="Graph not ready for this commit yet")

    return workspace.local_path
```

**Why this matters, concretely:**
- **`local_path` comes from the DB, never from a guessed or LLM-supplied path** — this is what every subagent's `repo_root` argument to CRG tools is actually resolved from. Nothing constructs a filesystem path from `repo_id` directly.
- **425, not a silent wait or a stale query** — if the graph isn't ready for this exact commit, subagents must not run against a graph that's mid-update or doesn't exist yet.

**Async note:** `graph_readiness_service` and the `RepoWorkspace` lookup are Phase 1 code — synchronous, by Phase 1's own design. Calling a sync DB read directly inside this phase's `async def` route would block the event loop for its duration. For a single fast SQLite read this is a minor, acceptable exception in practice — but if you want to keep the async layer strictly non-blocking, wrap the call: `await asyncio.to_thread(prepare_review_context, repo_id, graph_commit_hash)` from the route handler. Either is acceptable; pick one and be consistent, don't mix.

## Agent Contracts

```python
# domain/entities/agent_finding.py
from dataclasses import dataclass, field

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
```

**Confidence threshold:** a finding below 0.6 is low-confidence. Since there's no Context Agent yet to fetch more history, a low-confidence finding this phase is just surfaced as-is with its score visible — do not build any "fetch more context" fallback behavior; that's future-phase territory.

**Serialization for `AgentExecution.result`:** `AgentOutput`/`AgentFinding` are plain dataclasses — `json.dumps()` cannot serialize them directly, it raises `TypeError`. Convert first:

```python
import dataclasses, json

result_json = json.dumps(dataclasses.asdict(agent_output))
```

## Routing Policy

```yaml
review:
  agents: [compliance, security, performance, regression]

security_question:
  agents: [security]

impact_question:
  agents: [regression]

explain_question:
  agents: []   # orchestrator answers directly
```

`performance` must be present in the `review` entry — it was missing in an earlier draft of this policy; do not reproduce that omission.

## Event Schema (log only, no UI consumer yet)

```
{ type: "thinking", agent: "compliance", content: "..." }
{ type: "tool_call", agent: "compliance", tool: "query_graph_tool", input: {...} }
{ type: "tool_result", agent: "compliance", tool: "query_graph_tool", output: {...} }
{ type: "final", content: "..." }
```

---

## Folder Architecture (additive to Phase 1 — nothing below is deleted, everything from Phase 1 stays)

```
backend/src/code_review_agent/
│
├── domain/                                    # existing from Phase 1, extended
│   ├── entities/
│   │   ├── repo_workspace.py                  # (Phase 1, unchanged)
│   │   ├── graph_build_status.py              # (Phase 1, unchanged)
│   │   └── agent_finding.py                   # NEW — AgentFinding, AgentOutput
│   ├── repo/
│   │   └── repo_source_port.py                # (Phase 1, unchanged)
│   ├── graph/
│   │   └── graph_builder_port.py              # (Phase 1, unchanged)
│   └── review/                                 # NEW
│       ├── review_orchestrator_port.py         # NEW — async def run_review(...)
│       └── routing_policy.py                   # NEW — plain Python/YAML-loader, no framework import
│
├── application/                                # existing from Phase 1, extended
│   ├── repo_ingestion_service/                 # (Phase 1, unchanged)
│   ├── graph_build_service/                    # (Phase 1, unchanged)
│   └── review_service/                         # NEW
│       ├── prepare_review_context.py           # NEW — readiness check (425) + local_path resolution from DB
│       └── run_review.py                       # routes via routing_policy -> invokes ReviewOrchestratorPort
│
├── infrastructure/                             # existing from Phase 1, extended
│   ├── config.py                               # (Phase 1, extended with github_pat, context7_api_key, atlassian settings)
│   ├── repo_source/                            # (Phase 1, unchanged)
│   ├── graph_builder/                          # (Phase 1, unchanged)
│   ├── graph_service/                          # (Phase 1, unchanged)
│   ├── workspace/                              # (Phase 1, unchanged)
│   ├── db/
│   │   ├── models.py                           # (Phase 1 tables unchanged) + NEW ReviewSession, AgentExecution
│   │   └── engine.py                           # (Phase 1, EXTENDED — WAL pragma added, see SQLite note below)
│   ├── mcp_clients/                            # NEW
│   │   └── mcp_client_factory.py               # builds the shared MultiServerMCPClient
│   ├── agents_runtime/                         # NEW
│   │   ├── orchestrator_runtime.py             # create_deep_agent(...) wiring
│   │   ├── prompts/
│   │   │   ├── orchestrator.md
│   │   │   ├── compliance.md
│   │   │   ├── security.md
│   │   │   ├── performance.md
│   │   │   ├── regression.md
│   │   │   ├── fix_suggestion.md
│   │   │   └── aggregator.md
│   │   └── subagents/
│   │       ├── compliance_runtime.py           # builds the compliance_agent dict, scoped tools
│   │       ├── security_runtime.py
│   │       ├── performance_runtime.py
│   │       ├── regression_runtime.py
│   │       └── fix_suggestion_runtime.py
│   ├── event_bus/                              # NEW
│   │   └── log_event_bus.py                    # logs event schema to stdout/file, no streaming yet
│   └── api/
│       ├── models.py                           # NEW — ReviewRequest (Pydantic), Layer 2, not domain
│       └── routes/
│           ├── webhooks.py                     # (Phase 1, unchanged)
│           └── review.py                       # NEW — POST /review; calls prepare_review_context first, then dispatches agents
│
├── scripts/
│   ├── run_crg_server.sh                       # (Phase 1, unchanged)
│   └── run_atlassian_server.sh                 # NEW — `uvx mcp-atlassian --transport streamable-http --port 9000`
│
└── docker-compose.yaml                         # extended: add the mcp-atlassian service alongside existing volumes
```

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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AgentExecution(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    review_session_id: int = Field(foreign_key="reviewsession.id")
    agent_name: str
    duration_ms: int
    confidence: float | None = None
    result: str            # JSON-serialized via dataclasses.asdict() — see Agent Contracts above
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**Same fix applies to Phase 1's `RepoWorkspace`/`GraphSnapshot`/`GraphBuildStatus`** — they use the same deprecated `datetime.utcnow()` pattern. Not fixed here since it's outside this phase's scope, but worth doing before mixed naive/aware timestamps across tables in the same DB cause a real comparison bug — flag this in `OPENCODE.md` as a cross-phase cleanup item rather than leaving it unrecorded.

**Exception boundary — required, not optional.** If an LLM call fails or an MCP tool call times out mid-review, an unhandled exception must not skip the audit trail. Wrap the orchestration call so a failure still writes an `AgentExecution` row (`result="error"`-equivalent, with the exception message) before the route returns a 500:

```python
try:
    output = await run_review(...)
except Exception as exc:
    await record_agent_execution(review_session_id, agent_name="orchestrator", status="error", error=str(exc))
    raise HTTPException(status_code=500, detail="Review failed") from exc
```

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

- [ ] All 7 agents constructed via `create_deep_agent`, each subagent's `tools` list built by filtering `MultiServerMCPClient.get_tools()` output to exactly the names listed above — no agent has a tool outside its assigned set.
- [ ] Fix Suggestion has `refactor_tool` but explicitly does NOT have `apply_refactor_tool`.
- [ ] GitHub MCP client config includes `"X-MCP-Readonly": "true"` and a scoped `"X-MCP-Toolsets"` header — review agents never get a blanket "all GitHub tools" grant, server-side or client-side.
- [ ] `mcp-atlassian` is hardened server-side in both launch paths (script + compose) with `READ_ONLY_MODE=true` and `ENABLED_TOOLS=jira_get_issue,confluence_search,confluence_get_page`, and client-side Compliance is scoped to exactly `{jira_get_issue, confluence_search, confluence_get_page}` while Fix Suggestion is scoped to exactly `{confluence_search, confluence_get_page}` — no agent gets a blanket "all Jira/all Confluence" grant, server-side or client-side.
- [ ] Each GitHub-using agent's `allowed_names` set was checked against the live GitHub MCP tool registry (e.g. via `mcpcurl tools --help`) immediately before implementation, not copied from this doc unverified.
- [ ] Routing Policy includes `performance` in the `review` entry.
- [ ] `POST /review` validates its body against `ReviewRequest` (Pydantic, in `infrastructure/api/models.py` — not `domain/`).
- [ ] `POST /review` calls `prepare_review_context` before dispatching any agent: returns 404 for an unknown `repo_id`, returns 425 if the graph isn't ready for `graph_commit_hash` — verified by testing both failure cases, not just the happy path.
- [ ] Every subagent's `repo_root`/CRG tool calls use the `local_path` resolved from `RepoWorkspace` via `prepare_review_context` — never a guessed or independently-constructed filesystem path.
- [ ] `POST /review` runs orchestrator → subagents (per routing policy) → aggregator, returns a structured result.
- [ ] `MultiServerMCPClient` is constructed once at FastAPI startup (lifespan), not per-request.
- [ ] Phase 2's new tables (`ReviewSession`, `AgentExecution`) actually exist at runtime — satisfied by Phase 1's existing `init_db()`/`create_all` wiring once they're added to `db/models.py`, not by new startup code.
- [ ] A failed review still writes an `AgentExecution` row before returning a 500 — verified by forcing a failure (e.g. an invalid MCP URL) and checking the DB, not just reading the code.
- [ ] `ReviewSession` and `AgentExecution` rows are written per review, in the same SQLite DB as Phase 1, using timezone-aware (`datetime.now(timezone.utc)`) timestamps, not naive ones.
- [ ] `AgentExecution.result` is populated via `json.dumps(dataclasses.asdict(agent_output))`, not a raw `json.dumps(agent_output)` call.
- [ ] `review_model` is read from `settings`, has no hardcoded default anywhere in code, and is set via the `REVIEW_MODEL` env var.
- [ ] `tool_name_prefix` is left at its default (`False`) on `MultiServerMCPClient` — no prefix-stripping logic was added to `scoped()`.
- [ ] `db/engine.py` sets `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` on connection — required this phase due to `AgentExecution`'s higher write frequency, not optional.
- [ ] Event schema entries are logged (stdout/file) for thinking/tool_call/tool_result/final — no UI required.
- [ ] `mcp-atlassian` runs via `uvx mcp-atlassian --transport streamable-http --port 9000`, not the official Rovo server.
- [ ] Domain layer has zero imports of `deepagents`, `langchain_mcp_adapters`, or `fastapi`.
- [ ] Nothing from Phase 1's folder tree was deleted or modified except `config.py`, `db/models.py`, and `db/engine.py` (all extended, not replaced).
- [ ] No LangMem, no Context Agent, no conversation persistence tables, no frontend.
