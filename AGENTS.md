# AI Code Review Platform — Agent Coordination Rules

This project is built phase by phase. This file is the coordination hub — it declares which phase is currently active and holds rules that apply across all phases. Phase-specific detail lives in `PHASE_1.md`, `PHASE_2.md`, etc.

## Current Active Phase: Phase 2 — see `PHASE_2.md`

**Phase 1 is complete.** `PHASE_1.md` describes what was built (repo retrieval, CRG graph handling) — read it for context, but do not redo, modify, or re-verify it, except where `PHASE_2.md` explicitly says to extend it (`config.py`, `db/models.py`, `db/engine.py`). If Phase 1 appears broken while working on Phase 2, log it as a blocker in `OPENCODE.md` — do not silently "fix" Phase 1 code as a side effect of Phase 2 work.

## Mission Scope
**CRITICAL RESTRICTION:** build only what the current phase's file describes. Each phase file states its own out-of-scope list explicitly — treat it as binding. If asked to build something from a later phase, refuse and state it belongs there.

## When You're Unsure of a Library or MCP Server's Actual API — Use Context7, Don't Guess
Every agent in this project (`domain_architect`, `infra_engineer`, `reviewer`) is authorized to use the **Context7 MCP tool** whenever you're not certain of a library's exact function signature, an MCP server's real endpoint/transport/tool names, or any implementation detail you'd otherwise be inferring from training-data memory. This project has already been burned by confident-but-wrong claims about library behavior more than once — verify against Context7 (or the library's own current docs) before writing code that depends on the answer, not after something breaks.

This applies especially to: `deepagents`, `langchain-mcp-adapters`, `mcp` (the SDK), `code-review-graph`, `mcp-atlassian`, and any new library a phase file references.

## Do Not Expand Scope Beyond What a Phase File Specifies
If you find yourself wanting to introduce a new library, a new LLM provider, a new architectural abstraction, or any capability not named in the current phase file — **stop and log it as a blocker in `OPENCODE.md` for explicit confirmation.** Do not implement it speculatively, even if it seems like a reasonable improvement. This project has already had one such proposal (a multi-provider model factory) introduced without being asked for — treat that as the example of what not to repeat.

## If You Hit an Ambiguity
If something is not resolved by `AGENTS.md`, the current phase's `.md` file, or `OPENCODE.md`, **do not guess**. Log it under "Blockers / Pending Questions" in `OPENCODE.md` and stop that task.

## Subagent Execution Order
Run in this order, not in parallel, not reversed:
1. `domain_architect` — Layer 3/4 for the current phase.
2. `infra_engineer` — Layer 2/5, implemented against the ports `domain_architect` defined. Must not invent its own port shapes.
3. `reviewer` — audits the result against the current phase's Definition of Done.

## Services That Must Be Running for Phase 2 Work
- `code-review-graph serve --http --port 5555` (Phase 1)
- `uvx mcp-atlassian --transport streamable-http --port 9000` (Phase 2)

Both must be up before any agent runtime work can be tested end to end.

## The Async/Sync Boundary — Phase-Specific, and One Blended Case to Know About
**Phase 1 code is synchronous throughout** (see `PHASE_1.md`). Do not change it, do not retroactively make it async.

**Phase 2 code is async throughout.** `deepagents` and `langchain_mcp_adapters` are async-native; `POST /review` awaits directly rather than using `BackgroundTasks`.

**One blended case:** the review pre-flight (`PrepareReviewContextService` in `application/review_service/prepare_review_context.py`) runs synchronously from inside Phase 2's async route. It composes Phase 1's synchronous `GraphReadinessService` with two Layer 5 SQLModel adapters — `infrastructure/db/repo_workspace_repository.py` and `infrastructure/db/graph_status_repository.py` — all wired together by the Layer 2 route (`infrastructure/api/routes/review.py`). This is a deliberate, acceptable exception — a single fast SQLite read blocking briefly is fine — but it must not spread. Do not treat this as license to write other sync code in Phase 2; see `PHASE_2.md`'s note on this for the `asyncio.to_thread` alternative if strict non-blocking is preferred.

## Tech Stack & Tooling (cumulative across phases)
- **Phase 1:** FastAPI, uvicorn, SQLModel + SQLite, `subprocess`+git, `mcp` SDK (`mcp>=1.27,<2`), `filelock`, `pydantic-settings`.
- **Phase 2, added:** `deepagents`, `langchain-mcp-adapters`, `pydantic` (for `ReviewRequest`). MCP servers: CRG (5555, existing), `mcp-atlassian` (9000, new), GitHub MCP (remote-hosted, read-only via `X-MCP-Readonly`/`X-MCP-Toolsets` headers plus explicit per-agent tool lists — see Safety & Correctness Rules) and Context7 (remote-hosted, no local process).

## Safety & Correctness Rules — Do Not Relax These
- The Fix Suggestion agent gets `refactor_tool` (preview) but **never** `apply_refactor_tool` (applies a change). No agent gets write-capable tools without an explicit human-confirmation step outside its own tool list.
- GitHub MCP access is read-only by construction, enforced twice, deliberately redundant: server-side via `X-MCP-Readonly: true` and a scoped `X-MCP-Toolsets` header on the server config, and client-side via each agent's explicit, named tool list. No agent, in any phase, is ever granted "all GitHub tools" or unfiltered `get_tools(server_name="github")` output. Whenever GitHub's own tool names are referenced in a phase file, re-verify them against the live server (e.g. `mcpcurl tools --help`) before hardcoding — GitHub's tool naming has been consolidating.
- `tool_name_prefix` stays at its default (`False`) on `MultiServerMCPClient`. Do not add prefix-stripping or fuzzy tool-name-matching logic to `scoped()` — verified against the library's own docs that this default applies and no such stripping is needed; adding it anyway risks corrupting real tool names, since CRG's own names already contain underscores as part of the name itself.
- No hardcoded LLM model string anywhere in code. `review_model` is a required `settings` value, sourced from the `REVIEW_MODEL` env var (any `provider:model` spec resolvable by langchain's `init_chat_model`), with no default.
- `SubAgent` (from `deepagents`) is a `TypedDict` — plain dict literals are valid and correct. Do not wrap them in a typed class or expect Pydantic validation; there isn't any.
- The `crg` entry of `MultiServerMCPClient` must use `settings.crg_server_url` (Phase 1's env-configurable setting) — never a hardcoded `127.0.0.1` URL, since docker-compose overrides it to `http://crg-server:5555/mcp` and hardcoding silently breaks the container deployment.
- Table creation is already wired by Phase 1: `init_db()` (called in `main.py`'s lifespan) imports `infrastructure.db.models` wholesale and runs `SQLModel.metadata.create_all(engine)`. Later phases add new tables to `db/models.py` — they do **not** add new startup wiring to `db/engine.py` or `main.py`.
- `POST /review` must check graph readiness (425 if not ready) and resolve `repo_root` from the `RepoWorkspace` table before dispatching any agent — never from a guessed or constructed path.

## Webhook Ordering (Phase 1, still in effect)
Signature verification happens synchronously in the route handler, before `background_tasks.add_task(...)` — never inside the deferred task.

## Deployment
All workspace/DB/graph storage sits on named persistent volumes in `docker-compose.yaml` — never network-shared storage. CRG runs as its own service, not auto-launched by the app process (see `crg_server_manager.py`'s role: a startup connectivity check, not a launcher).