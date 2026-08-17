# AI Code Review Platform — Agent Coordination Rules

This project is built phase by phase. This file is the coordination hub — it declares which phase is currently active and holds rules that apply across all phases. Phase-specific detail lives in `PHASE_1.md`, `PHASE_2.md`, `PHASE_3.md`, etc.

## Current Active Phase: Phase 3 — see `PHASE_3.md`

**Phase 1 and Phase 2 are complete.** `PHASE_1.md` and `PHASE_2.md` describe what was built (repo retrieval, CRG graph handling, multi-agent review core) — read them for context, but do not redo, modify, or re-verify them, except where `PHASE_3.md` explicitly authorizes extensions (`infrastructure/db/models.py`, `infrastructure/db/engine.py`, `infrastructure/mcp_clients/mcp_client_factory.py`, `config.py`). If Phase 1 or 2 code appears broken while working on Phase 3, log it as a blocker in `OPENCODE.md` — do not silently "fix" legacy code as a side effect.

## Mission Scope
**CRITICAL RESTRICTION:** build only what the current phase's file describes. Each phase file states its own out-of-scope list explicitly — treat it as binding. If asked to build something from a later phase or unapproved speculative features, refuse and state it belongs in future specifications.

## When You're Unsure of a Library or MCP Server's Actual API — Use Context7, Don't Guess
Every agent in this project (`domain_architect`, `infra_engineer`, `reviewer`) is authorized to use the **Context7 MCP tool** whenever you're not certain of a library's exact function signature, an MCP server's real endpoint/transport/tool names, or any implementation detail you'd otherwise be inferring from training-data memory. Verify against Context7 (or the library's own current docs) before writing code that depends on the answer, not after something breaks.

This applies especially to: `deepagents`, `langchain-mcp-adapters`, `mcp` (including `mcp.server.fastmcp`), `code-review-graph`, `mcp-atlassian`, and SQLite FTS5 syntax.

## Do Not Expand Scope Beyond What a Phase File Specifies
If you find yourself wanting to introduce a new library, a new LLM provider, a vector database (e.g. ChromaDB/RAG), or any capability not named in the current phase file — **stop and log it as a blocker in `OPENCODE.md` for explicit confirmation.** Do not implement it speculatively, even if it seems like a reasonable improvement.

## If You Hit an Ambiguity
If something is not resolved by `AGENTS.md`, `PHASE_3.md`, or `OPENCODE.md`, **do not guess**. Log it under "Blockers / Pending Questions" in `OPENCODE.md` and stop that task.

## Subagent Execution Order
Run in this order, not in parallel, not reversed:
1. `domain_architect` — Layer 3/4 for the current phase (`domain/entities/`, `application/conversation_service/`).
2. `infra_engineer` — Layer 2/5, implemented against the ports/entities `domain_architect` defined (`infrastructure/db/models.py`, `infrastructure/mcp_clients/servers/`, `infrastructure/agents_runtime/`). Must not invent its own port shapes.
3. `reviewer` — audits the result against the current phase's Definition of Done.

## Services That Must Be Running for Phase 3 Work
- `code-review-graph serve --http --port 5555` (Phase 1)
- `uvx mcp-atlassian --transport streamable-http --port 9000` (Phase 2)
- Conversation FastMCP Server (Phase 3 — internal streamable HTTP port bound to `127.0.0.1`)

All must be running before agent runtime and conversation workflows can be tested end-to-end.

## The Async/Sync Boundary — Phase Rules
- **Phase 1 code is synchronous throughout** (see `PHASE_1.md`). Do not change it retroactively.
- **Phase 2 and Phase 3 application routes are async.**
- **Threadpool Offloading for SQLite & FastMCP:** FastMCP tool executions and synchronous SQLite persistence calls must be wrapped using `run_in_threadpool` or executed via async sessions to preserve FastAPI event loop performance.

## Tech Stack & Tooling (cumulative across phases)
- **Phase 1:** FastAPI, uvicorn, SQLModel + SQLite, `subprocess`+git, `mcp` SDK (`mcp>=1.27,<2`), `filelock`, `pydantic-settings`.
- **Phase 2, added:** `deepagents`, `langchain-mcp-adapters`, `pydantic`. MCP servers: CRG (5555), `mcp-atlassian` (9000), GitHub MCP (read-only), Context7.
- **Phase 3, added:** `mcp.server.fastmcp` (FastMCP server runtime), SQLite FTS5 virtual tables (`message_fts` with `porter unicode61 tokenchars '_-.'`), conversation persistence (`Conversation`, `Message`, `ToolCall`, `MemorySummary`).

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