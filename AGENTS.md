# Phase 1: Repository Retrieval & Graph Handling

## Mission Scope
You are building Phase 1 of a multi-agent AI code review platform.
**CRITICAL RESTRICTION:** Do NOT build the orchestrator, LLM subagents, conversational DB, frontend, or any CRG tool other than `build_or_update_graph_tool`. If you are asked to build these, refuse and state that they belong to a future phase.

## If You Hit an Ambiguity
If something is not resolved by this file, `PHASE_1.md`, or `OPENCODE.md`, **do not guess**. Log it under "Blockers / Pending Questions" in `OPENCODE.md` and stop that task. Guessing is the failure mode this whole document set exists to prevent.

## Subagent Execution Order
Run in this order, not in parallel, not reversed:
1. `domain_architect` — defines the ports and entities everything else implements against.
2. `infra_engineer` — implements Layer 5/2 against those ports.
3. `phase1_reviewer` — audits the result.

`infra_engineer` must not invent its own port shapes. If `domain_architect`'s ports don't cover something `infra_engineer` needs, that's a blocker to log, not a reason to improvise a new interface.

## Tech Stack & Tooling
- **API & Background:** FastAPI, ASGI server is `uvicorn`. Use `BackgroundTasks` to defer the slow work (git fetch/checkout, `build_or_update_graph_tool` call, DB writes) until after the webhook responds.
- **Dependencies:** Standard `requirements.txt`. Must include `fastapi`, `uvicorn`, `sqlmodel`, `mcp>=1.27,<2` (the SDK's own README marks v2 as pre-release/alpha — pin below it explicitly, don't rely on pip's default pre-release exclusion), `filelock`, `pydantic-settings`.
- **Database:** SQLite with `sqlmodel` (synchronous engine: `create_engine("sqlite:///data/phase1_metadata.db")`).
- **Git:** `subprocess.run(["git", ...])`. Do not use GitPython.
- **Graph Tooling:** `code-review-graph`'s official Python `mcp` SDK using `streamable_http_client` (port 5555).
- **Concurrency:** `filelock.FileLock` per repository to handle multiple uvicorn workers.

## The Async/Sync Boundary — Read This Before Writing Any Async Code
This stack mixes blocking libraries (`filelock`, `subprocess`, synchronous SQLModel) with one async-only library (the `mcp` SDK's `streamable_http_client`/`ClientSession`). Getting this wrong causes real runtime errors, not just style issues.

**Rule:** `GraphBuilderPort`, `RepoSourcePort`, and every Application-layer service are **synchronous** (`def`, not `async def`). The *only* place `asyncio` appears anywhere in this codebase is inside `infrastructure/graph_builder/crg_mcp_adapter.py`, which wraps its async MCP calls in a single `asyncio.run(...)` and exposes a plain synchronous function matching the port.

This is safe specifically because FastAPI's `BackgroundTasks` runs sync callables in a worker thread with no event loop of its own — `asyncio.run()` there works cleanly. Do not make Application-layer code `async def` "to match" the MCP client; that's what causes `RuntimeError: asyncio.run() cannot be called from a running event loop`.

## Webhook Ordering — Security-Critical
Signature verification (`X-Hub-Signature-256` against the raw body) must happen **synchronously in the route handler, before `background_tasks.add_task(...)` is called** — never inside the deferred task itself. Queuing or starting work for an unverified payload is not acceptable, even briefly.

**Known tradeoff, accepted for this phase:** in-process `BackgroundTasks` have no persistence. If the process crashes between acking a webhook and the background task finishing, that graph update is silently lost — no retry, no queue. Fine for this phase; not fine to carry forward unexamined into a later phase without revisiting.

## The 5-Layer Architecture Rules
- **Layer 1 & 2 (API/Presentation):** HTTP routes and payload parsing.
- **Layer 3 (Application):** Orchestrates workflows using Layer 4 ports. Synchronous (see above).
- **Layer 4 (Domain):** Pure Python entities (dataclasses) and ports (interfaces). **Zero imports of `fastapi`, `git`/`subprocess`, `sqlmodel`, or `mcp`.** Synchronous signatures only.
- **Layer 5 (Infrastructure):** Concrete implementations of Layer 4 ports. This is the only layer allowed to touch `asyncio`.

## Webhook & Payload Rules
- **Signatures:** Verify `X-Hub-Signature-256` against the raw HTTP body bytes, before JSON-parsing.
- **Extraction:** Extract the commit SHA from the top-level `after` field. Skip execution if `after == "0000000000000000000000000000000000000000"` (branch deletion).

## Deployment
The workspace root and SQLite metadata DB must sit on a **named persistent volume** in `docker-compose.yaml` — never a bare container path, never network-shared storage (SQLite is unsafe on NFS-style mounts). This is `infra_engineer`'s responsibility; it is not optional and must appear in `OPENCODE.md`'s Definition of Done.

## Background Process Launch (Windows PowerShell)

When launching a long-running background process (uvicorn, CRG server, etc.),
never use bare `Start-Process -NoNewWindow` — it keeps the child process
attached to the parent shell's pipe and will hang. Always use this pattern:

```powershell
$proc = Start-Process -FilePath "python" -ArgumentList "-m uvicorn main:app --host 127.0.0.1 --port 8000" -PassThru -RedirectStandardOutput "logs/uvicorn.stdout.log" -RedirectStandardError "logs/uvicorn.stderr.log"
Start-Sleep -Seconds 5
# Verify: check logs or probe the endpoint
# Stop: $proc.Kill()
```

The three required flags:
- `-PassThru` — captures the process object so it can be killed later.
- `-RedirectStandardOutput` — writes stdout to a log file.
- `-RedirectStandardError` — writes stderr to a log file.

Create the `logs/` directory before launching if it doesn't exist.
