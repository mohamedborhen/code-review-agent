# AI Code Review Platform — Agent Coordination Rules

This project is built phase by phase. This file is the coordination hub — it declares which phase is currently active and holds rules that apply across all phases. Phase-specific detail lives in `PHASE_1.md`, `PHASE_2.md`, `PHASE_3.md`, `PHASE_4.md`, and `PHASE_5_FRONTEND.md`.

## Current Active Phase: Phase 5 (Frontend) — see `PHASE_5_FRONTEND.md`

**Phases 1–4 are complete.** `PHASE_1.md`, `PHASE_2.md`, `PHASE_3.md`, and `PHASE_4.md` describe what was built (repo retrieval, CRG graph handling, multi-agent review core, stateful conversations + FTS5 recall, summarization + long-term memory) — read them for context, but do not redo, modify, or re-verify them. If backend code appears broken while working on Phase 5, log it as a blocker in `OPENCODE.md` — do not silently "fix" it as a side effect.

**Phase 5 is the final phase — frontend + minimal backend vault.** `PHASE_5_FRONTEND.md` is ground truth, but Decision 7 of the approved 2026-08-25 8-item plan explicitly authorizes a **narrow backend exception** for the credential vault only: `RepoCredential` (Fernet, `CREDENTIAL_ENCRYPTION_KEY`), `RepoWorkspace.repo_url`, per-repo HMAC, per-request PAT/Jira headers, and the Jira URL spike override. All other backend code remains frozen. New exceptions beyond this list still require explicit authorization.

**Frontend-only default still applies outside that vault:**

- **The backend has no CORS middleware** (verified: zero matches for `CORSMiddleware`/`add_middleware` across `backend/`). Phase 5 resolves this with a **Vite dev proxy** (`PHASE_5_FRONTEND.md` §8.4/§9.4), *not* by adding middleware to `main.py`. Adding it would be a backend change requiring explicit authorization.
- **Missing endpoints stay missing.** `PHASE_5_FRONTEND.md` §3 lists what does not exist (no `GET /api/v1/repos` of any kind, no readiness probe, no auth, no Atlassian OAuth, no webhook registration). Each has a stub contract in §4. Do not build a backend endpoint to fill a frontend gap.

### Ground truth for API shapes in Phase 5
`PHASE_5_FRONTEND.md` Section 2 was audited directly against the running backend source (file:line citations inline) and **supersedes `PHASE_2.md`/`PHASE_3.md` wherever they differ.** Those older docs contain at least two shapes the implementation has since diverged from. Four specifics that were wrong in earlier documentation and must not be re-introduced:

- **All routes are under `/api/v1`** (`main.py:50-52`) — there are exactly 8.
- **`GET /api/v1/repos/{repo_id:path}/branches` returns a wrapped object**, not a bare array (`webhooks.py:176`).
- **`AgentFinding.severity` is an open string**, not a 3-value union — a live review returned six distinct values (`agent_finding.py:18`, `report_schema.py:17`).
- **`question` is forwarded for `request_type: "review"`** (`orchestrator_message.py:15-17,75`); only `explain_question` drops it.

### The Stitch export is the visual source of truth
`stitch_reviewmind_ai_developer_platform/` holds 5 HTML screens, 5 matching PNGs, and `DESIGN.md`. **HTML and PNG together are binding** — HTML for structure/classes/tokens, PNG for what actually renders. They were audited and agree on every screen. **Do not recreate UI absent from the export**, and do not request a re-export. `PHASE_5_FRONTEND.md` §7.3 records what was formally cut (the six sidebar request-type shortcuts, "Run Analysis", the composer attach/code-snippet buttons); §7.4 records fabricated content not to wire.

## Mission Scope
**CRITICAL RESTRICTION:** build only what the current phase's file describes. Each phase file states its own out-of-scope list explicitly — treat it as binding. If asked to build something from a later phase or unapproved speculative features, refuse and state it belongs in future specifications.

## When You're Unsure of a Library or MCP Server's Actual API — Use Context7, Don't Guess
Every agent in this project (`domain_architect`, `infra_engineer`, `reviewer`) is authorized to use the **Context7 MCP tool** whenever you're not certain of a library's exact function signature, an MCP server's real endpoint/transport/tool names, or any implementation detail you'd otherwise be inferring from training-data memory. Verify against Context7 (or the library's own current docs) before writing code that depends on the answer, not after something breaks.

This applies especially to: `deepagents`, `langchain-mcp-adapters`, `mcp` (including `mcp.server.fastmcp`), `code-review-graph`, `mcp-atlassian`, and SQLite FTS5 syntax. **For Phase 5 add:** Tailwind CSS (**check the major version first** — the Stitch export is v3-style with a JS config; v4 is CSS-first with no JS config, and the port differs completely), `vite-plugin-pwa`, Vite's `server.proxy` options, `react-router`, and `idb`.

## Do Not Expand Scope Beyond What a Phase File Specifies
If you find yourself wanting to introduce a new library, a new LLM provider, a vector database (e.g. ChromaDB/RAG), or any capability not named in the current phase file — **stop and log it as a blocker in `OPENCODE.md` for explicit confirmation.** Do not implement it speculatively, even if it seems like a reasonable improvement.

## If You Hit an Ambiguity
If something is not resolved by `AGENTS.md`, `PHASE_5_FRONTEND.md`, or `OPENCODE.md`, **do not guess**. Log it under "Blockers / Pending Questions" in `OPENCODE.md` and stop that task.

## Subagent Execution Order
Run in this order, not in parallel, not reversed. Agent files are cached when a session starts — put them in place **before** kicking off, not mid-session.

**Phase 5 (current):**
1. `domain_architect` — API types, hook contracts, state design, stub shapes (`frontend/src/types/`, `frontend/src/state/`, `frontend/src/hooks/` contracts).
2. `infra_engineer` — components, API client, wiring, Vite/PWA config, implemented against the contracts `domain_architect` defined. Must not invent its own shapes. **Stops after Stage 5a** for review before wiring.
3. `reviewer` — audits at each stage boundary (5a / 5b / 5c) against `PHASE_5_FRONTEND.md` §11.

**Phases 1–4 (historical):** `domain_architect` covered Layer 3/4 (`domain/entities/`, `application/`), `infra_engineer` Layer 2/5 (`infrastructure/`), `reviewer` the phase DoD.

## Services That Must Be Running for Phase 5 Work
- `code-review-graph serve --http --port 5555` (Phase 1)
- `uvx mcp-atlassian --transport streamable-http --port 9000` (Phase 2)
- Conversation FastMCP Server on `127.0.0.1:9001` — `python -m infrastructure.mcp_clients.servers.conversation_server` (Phase 3)
- The FastAPI app itself — `python -m uvicorn main:app --host 127.0.0.1 --port 8000` (from `backend/src/code_review_agent/`)
- The Vite dev server, proxying `/api/v1` → `127.0.0.1:8000` (Phase 5)

All must be running before a chat turn can be tested end-to-end. Note the app's startup lifespan **fails hard** if CRG is unreachable (`main.py:28`), so start CRG first.

**Observed review latencies** (real runs, for calibrating "still working" UI — not a target): 186s for a single-specialist `compliance_question`, 455s for a 4-specialist `review`.

## The Async/Sync Boundary — Phase Rules
- **Phase 1 code is synchronous throughout** (see `PHASE_1.md`). Do not change it retroactively.
- **Phase 2, 3, and 4 application routes are async.**
- **Threadpool Offloading for SQLite & FastMCP:** FastMCP tool executions and synchronous SQLite persistence calls must be wrapped using `run_in_threadpool` or executed via async sessions to preserve FastAPI event loop performance.
- **Phase 5 is client-side** — this boundary does not apply, but note `POST /api/v1/review` is **fully synchronous** and blocks for the entire review. It is the sole source of the final answer; the polling endpoints are progress-only.

## Tech Stack & Tooling (cumulative across phases)
- **Phase 1:** FastAPI, uvicorn, SQLModel + SQLite, `subprocess`+git, `mcp` SDK (`mcp>=1.27,<2`), `filelock`, `pydantic-settings`.
- **Phase 2, added:** `deepagents`, `langchain-mcp-adapters`, `pydantic`. MCP servers: CRG (5555), `mcp-atlassian` (9000), GitHub MCP (read-only), Context7.
- **Phase 3, added:** `mcp.server.fastmcp` (FastMCP server runtime), SQLite FTS5 virtual tables (`message_fts` with `porter unicode61 tokenchars '_-.'`), conversation persistence (`Conversation`, `Message`, `ToolCall`, `MemorySummary`).
- **Phase 4, added:** `langmem`, `langgraph-checkpoint-sqlite` (`AsyncSqliteStore`, no vector index), `langchain-nvidia-ai-endpoints`, explicit `SummarizationMiddleware`, `ReviewToolCall` persistence.
- **Phase 5, added (frontend only):** React, Vite, TypeScript, Tailwind (via Vite/PostCSS — **never** the Play CDN), `vite-plugin-pwa`, a router, `idb` for IndexedDB caches.

## Safety & Correctness Rules — Do Not Relax These

### Agent & Tool Permissions
- The Context Agent is **strictly read-only**, full stop. It is granted ONLY `["search_messages"]`. No write tools (INSERT/UPDATE/DELETE), no `execute_sql` tool, and no vector/RAG tools are ever exposed to it.
- The Fix Suggestion agent gets `refactor_tool` (preview) but **never** `apply_refactor_tool` (applies a change). No agent gets write-capable tools without explicit human-confirmation steps outside its own tool list.
- GitHub MCP access is read-only by construction, enforced twice: server-side (`X-MCP-Readonly: true` + `X-MCP-Toolsets`) and client-side via explicit named tool lists. No agent is ever granted "all GitHub tools" or unfiltered `get_tools(server_name="github")` output.
- `tool_name_prefix` stays at its default (`False`) on `MultiServerMCPClient`. Do not add prefix-stripping or fuzzy matching to `scoped()`.

### Codebase Structure & Database Rules
- **File Placement Discipline:** All ORM models MUST be appended to `infrastructure/db/models.py`. Never create an `infrastructure/db/models/` directory (collides with module imports).
- **Startup Wiring Exception:** An explicit, documented exception is granted in `infrastructure/db/engine.py` to run raw DDL during `init_db()` for the `message_fts` virtual table, 3 sync triggers (`message_ai`, `message_ad`, `message_au`), and the `_rebuild_agentexecution()` 4-step table rebuild migration script.
- **Static MCP Client & Identity Transport:** `MultiServerMCPClient` is constructed once at FastAPI startup (`app.state`). Dynamic identity (`user_id`, `repo_id`) is passed as explicit typed parameters into `search_messages`, injected and authorized by Layer 3 Application orchestration.
- **FTS5 Query Protection:** Input queries in `search_messages` MUST be phrase-quoted (`'"' + query.replace('"', '""') + '"'`) before running FTS `MATCH` statements to prevent SQLite `OperationalError` when searching hyphenated terms (e.g. `CLIP-4`).
- **Audit Privacy:** Context Agent invocations are logged to `AgentExecution` via `json.dumps(dataclasses.asdict())`. **Never log message content or snippet text** into audit tables.
- **Model Configuration:** No hardcoded LLM model strings. `review_model` is sourced from `REVIEW_MODEL` env var via `settings`.

## Webhook Ordering (Phase 1, still in effect)
Signature verification happens synchronously in the route handler, before `background_tasks.add_task(...)` — never inside the deferred task.

## Deployment
All workspace/DB/graph storage sits on named persistent volumes in `docker-compose.yaml`. CRG runs as its own service, verified via startup connectivity checks.