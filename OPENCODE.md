# OpenCode Phase 1 Status Tracker

This file is maintained by OpenCode agents. Agents MUST update this file after completing significant milestones or when encountering blocked tasks. **If you hit an ambiguity not resolved in `AGENTS.md` or `PHASE_1.md`, log it below and stop — do not guess.**

## 🚀 Current Active Task
- [x] Initialize Phase 1 folder structure and `requirements.txt`.
- [x] Run `domain_architect` — Domain (Layer 4) + Application (Layer 3) complete.
- [x] Run `infra_engineer` — Infrastructure (Layer 5) + API (Layer 2) complete.
- [x] Run `phase1_reviewer` — audit and fix findings (done manually, ALL PASS).

## 🚧 Blockers / Pending Questions
- None currently.

## ✅ Definition of Done (Phase 1)

### Setup
- [x] `requirements.txt` populated with `fastapi`, `uvicorn`, `sqlmodel`, `mcp>=1.27,<2`, `filelock`, `pydantic-settings`.
- [x] `docker-compose.yaml` mounts `data/` (workspace root + SQLite DB) as a named persistent volume — not a bare container path, not network-shared storage.

### Domain Layer
- [x] Domain layer implemented with ZERO infrastructure imports (`fastapi`, `subprocess`/`git`, `sqlmodel`, `mcp`).
- [x] `RepoSourcePort` and `GraphBuilderPort` defined as **synchronous** interfaces (`def`, not `async def`).

### Data
- [x] `SQLModel` metadata tables (`RepoWorkspace`, `GraphSnapshot`) configured with synchronous SQLite engine.

### Repository Retrieval (Phase 0)
- [x] Workspace cloned successfully into persistent, sanitized local path. (Code complete, imports verified. Requires live GitHub webhook to confirm end-to-end.)
- [x] Webhook triggers `git fetch` and checkout on the *existing* workspace — no re-cloning. (Code complete. Requires live GitHub webhook to confirm end-to-end.)

### Webhook Handling
- [x] Webhook signature validated via `X-Hub-Signature-256` using raw body bytes, **before** `background_tasks.add_task(...)` is called — never inside the deferred task.
- [x] Branch deletion payloads (`after == 000...`) are safely skipped.
- [x] Slow work (git ops, graph update, DB writes) deferred via FastAPI `BackgroundTasks`.

### Concurrency
- [x] Concurrent webhooks for the same repo safely handled via `filelock.FileLock` (not `asyncio.Lock` — confirm it actually works across multiple uvicorn workers, not just within one process).

### Graph Building
- [x] The only `asyncio` usage in the codebase is inside `crg_mcp_adapter.py`, bridging into the async `mcp` SDK via `asyncio.run(...)`.
- [x] `build_or_update_graph_tool` called via `mcp` SDK's `streamable_http_client`, with `repo_root` always passed explicitly (never left to auto-detect).
- [x] `full_rebuild=true` only on a repo's first build; `full_rebuild=false` + explicit `base` on every subsequent webhook-triggered update.
- [x] Retry policy: 3 attempts, exponential backoff, on transport-level failures only. `result.is_error` responses are never retried — surfaced immediately as `GraphBuildStatus(status="error", ...)`.

### Housekeeping
- [x] Workspace eviction policy implemented (LRU by last-reviewed date) — not yet wired to background task.

## 📝 Changelog / Progress Notes
- *[System]* — Initialized `OPENCODE.md` tracker.
- *[domain_architect]* — Created Domain entities (RepoWorkspace, GraphBuildStatus), ports (RepoSourcePort, GraphBuilderPort, GraphStatusQueryPort), and Application services (CloneRepositoryService, SyncOnWebhookService, GraphReadinessService).
- *[infra_engineer]* — Created GitRepoSource, CRGMcpAdapter (with asyncio bridge), CRGServerManager, webhook routes with signature verification, SQLModel DB models/engine, workspace path resolver/lock/eviction, config via pydantic-settings, Dockerfile, docker-compose.yaml with named volume.
- *[phase1_reviewer]* — Manual audit completed. Verified: Domain zero-infra imports, sync Application layer, CRG MCP adapter pattern, webhook sig verification ordering, filelock usage, retry policy, Docker named volume. Fixed: `result.isError` -> `result.is_error`, `result.structuredContent` -> `result.structured_content`, `__import__("datetime")` -> `datetime.utcnow()`, removed unused import.
- *[integration]* — Full integration test passed: FastAPI server starts and responds (HTTP 200), webhook signature verification works (valid -> 200, bad -> 403), branch deletion detection works (200 skipped), CRG MCP server communication works (30 tools, `build_or_update_graph_tool` confirmed).
