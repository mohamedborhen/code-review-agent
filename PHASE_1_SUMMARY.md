# Phase 1 — Code Review Agent: Comprehensive Implementation Summary

## 1. Project Overview

Phase 1 builds the **repository retrieval and graph handling** layer of a multi-agent AI code review platform. It provides a webhook-based service that:

1. Receives GitHub push events
2. Clones or synchronizes repositories to local disk
3. Builds and incrementally updates a structural code knowledge graph using `code-review-graph`
4. Persists metadata (workspaces, build snapshots) to SQLite

**Critical restriction:** Only `build_or_update_graph_tool` from the CRG suite is implemented. All other tools (flows, communities, impact analysis) are reserved for Phase 2 subagents.

---

## 2. Architecture: 5-Layer Design

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 1 & 2 — API / Presentation                                   │
│  infrastructure/api/routes/webhooks.py                              │
│  FastAPI endpoints, request parsing, BackgroundTasks scheduling     │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 3 — Application                                              │
│  application/repo_ingestion_service/                                │
│  Synchronous orchestration: clone→build, fetch→update               │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 4 — Domain                                                   │
│  domain/entities/ domain/graph/ domain/repo/                        │
│  Pure Python dataclasses + Protocol interfaces. ZERO infra imports. │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 5 — Infrastructure                                           │
│  infrastructure/graph_builder/ repo_source/ workspace/ db/          │
│  Concrete implementations. ONLY layer with asyncio.                 │
└─────────────────────────────────────────────────────────────────────┘
```

### The Async/Sync Boundary (Critical Design)

```
BackgroundTasks (sync thread) ──→ asyncio.run() ──→ MCP SDK (async)
    no event loop here              creates fresh         streamable_http_client
                                    event loop            ClientSession.call_tool()
```

- `GraphBuilderPort`, `RepoSourcePort`, and all Application services are **synchronous** (`def`, not `async def`).
- The **only** `asyncio` in the codebase is inside `crg_mcp_adapter.py:42` — a single `asyncio.run(_call_crg_async(...))`.
- This is safe because `BackgroundTasks` runs sync callables in a worker thread with no event loop of its own.
- **Do NOT make Application-layer code `async def`** to "match" the MCP client — that causes `RuntimeError: asyncio.run() cannot be called from a running event loop`.

---

## 3. Complete Directory Structure with File Roles

```
AI code reviewer agent/
│
├── backend/src/code_review_agent/          # ◄── Root of the Python package
│   ├── main.py                             # FastAPI app creation, lifespan (init_db + verify CRG),
│   │                                       #     router wiring (prefix=/api/v1)
│   │
│   ├── .env                                # Local secrets (gitignored):
│   │                                       #     GITHUB_WEBHOOK_SECRET, CRG_SERVER_URL,
│   │                                       #     WORKSPACE_ROOT, METADATA_DB_PATH
│   │
│   ├── domain/                             # ═══ LAYER 4: PURE DOMAIN ═══
│   │   ├── entities/
│   │   │   ├── repo_workspace.py           # Dataclass: repo_id, local_path,
│   │   │   │                               #     last_synced_commit, timestamps
│   │   │   └── graph_build_status.py       # Dataclass: commit_hash, status,
│   │   │                                   #     error_message, timestamps
│   │   ├── graph/
│   │   │   └── graph_builder_port.py       # Protocol: build(repo_root) → GraphBuildStatus
│   │   │                                   #           update(repo_root, base) → GraphBuildStatus
│   │   └── repo/
│   │       └── repo_source_port.py         # Protocol: clone(repo_url, local_path) → str(sha)
│   │                                       #           sync(local_path, ref) → str(sha)
│   │                                       #           create_worktree / update_worktree / current_branch (D-8)
│   │
│   ├── application/                        # ═══ LAYER 3: APPLICATION ═══
│   │   ├── repo_ingestion_service/
│   │   │   ├── clone_repository.py         # CloneRepositoryService:
│   │   │   │                               #     1. Sanitize repo_id → safe filesystem name
│   │   │   │                               #     2. GitRepoSource.clone(repo_url, path)
│   │   │   │                               #     3. CRGMcpAdapter.build(repo_root) [full_rebuild=true]
│   │   │   │                               #     4. Return (RepoWorkspace, GraphBuildStatus)
│   │   │   └── sync_on_webhook.py          # SyncOnWebhookService:
│   │   │                                   #     1. GitRepoSource.sync(path, ref) [fetch + checkout]
│   │   │                                   #     2. CRGMcpAdapter.update(repo_root, base) [incremental]
│   │   │                                   #     3. Return GraphBuildStatus
│   │   └── graph_build_service/
│   │       └── graph_readiness_service.py  # GraphReadinessService:
│   │                                       #     Query GraphSnapshot by repo_id + commit_hash
│   │                                       #     Return bool: is graph ready? (for Phase 2)
│   │   └── repo_ingestion_service/ensure_branch_worktree.py  # NEW (Branch-Aware §5)
│   │                                       #     EnsureBranchWorktreeService: create/update worktree
│   │                                       #     + build/update graph; records last_synced_commit +
│   │                                       #     GraphSnapshot; releases per-branch lock in finally
│   │
│   └── infrastructure/                     # ═══ LAYER 5+2: INFRASTRUCTURE + API ═══
│       ├── config.py                       # pydantic-settings BaseSettings
│       │                                   #     Reads .env, resolves relative paths
│       │                                   #     via __file__ (not CWD) for consistency
│       │
│       ├── api/routes/
│       │   └── webhooks.py                 # POST /api/v1/webhook  — GitHub push events
│       │                                   # POST /api/v1/repos    — Register new repo
│       │                                   # GET /api/v1/repos/{repo_id}/branches  — NEW (read-only proxy)
│       │                                   # HMAC-SHA256 verification (sync, before add_task)
│       │                                   # Branch-aware: process_webhook no-ops for non-default branch
│       │                                   # BackgroundTasks for slow work
│       │
│       ├── db/
│       │   ├── engine.py                   # create_engine("sqlite:///...") — synchronous
│       │   │                               #     init_db(): SQLModel.metadata.create_all(engine)
│       │   └── models.py                   # SQLModel table classes:
│       │                                   #     RepoWorkspace(id, repo_id, branch, local_path,
│       │                                   #         last_synced_commit, last_requested_at, created_at, updated_at)
│       │                                   #         UNIQUE(repo_id, branch) — one row per branch (Branch-Aware)
│       │                                   #     GraphSnapshot(id, repo_id, commit_hash,
│       │                                   #         status, error_message, started_at, completed_at)
│       │
│       ├── graph_builder/
│       │   └── crg_mcp_adapter.py          # CRGMcpAdapter implements GraphBuilderPort
│       │                                   #     Uses mcp SDK: streamable_http_client + ClientSession
│       │                                   #     asyncio.run() bridge (only asyncio in codebase)
│       │                                   #     Retry: 3 attempts, exponential backoff
│       │                                   #     Transport errors retried; tool errors surfaced immediately
│       │
│       ├── graph_service/
│       │   └── crg_server_manager.py       # ensure_connected(): startup connectivity check
│       │                                   #     via MCP ping; fails loudly if CRG unavailable
│       │                                   #     No subprocess launch (CRG runs separately
│       │                                   #     in Docker or started manually in local dev)
│       │
│       ├── repo_source/
│       │   └── git_repo_source.py          # GitRepoSource implements RepoSourcePort
│       │                                   #     subprocess.run(["git", ...])
│       │                                   #     clone: shutil.rmtree stale dirs first
│       │                                   #     _run_git: manual returncode check + stderr in RuntimeError
│       │                                   #     create_worktree: fetch <b>:<b> then git worktree add (shallow-clone fix)
│       │                                   #     update_worktree: fetch + reset --hard origin/<b>; returns HEAD sha
│       │
│       └── workspace/
│           ├── workspace_lock.py           # acquire_workspace_lock: FileLock(/.{safe}.lock)
│           │                               #     Lock file OUTSIDE workspace dir (avoids Windows
│           │                               #     PermissionError on locked files during shutil.rmtree)
│           │                               #     branch=None keeps default key; per-branch key .{safe}_{safe_branch}.lock
│           │                               #     try_acquire_lock: timeout=0 non-blocking probe (Branch-Aware §8)
│           ├── workspace_path_resolver.py  # sanitize_repo_id + resolve_workspace_path + resolve_worktree_path
│           └── workspace_eviction_service.py # Worktree-aware LRU by last_requested_at (Branch-Aware §11):
│                                             #     git worktree remove + prune for worktrees, rmtree fallback;
│                                             #     base clone resolved as sibling {root}/{safe_id}; wired to lifespan
│
├── docker-compose.yaml                     # Two services + named volume + healthcheck
│                                           #     code-review-agent (port 8000, depends_on with
│                                           #       condition: service_healthy, CRG_SERVER_URL
│                                           #       overridden to http://crg-server:5555/mcp)
│                                           #     crg-server (port 5555 internal only, socket
│                                           #       healthcheck via /dev/tcp, no host exposure)
│                                           #     workspace_data:/app/data
│
├── Dockerfile                              # python:3.12-slim, git, pip install, uvicorn CMD
├── Dockerfile.crg                          # Same base, installs deps for CRG server (code-review-graph serve)
│
├── requirements.txt                        # 7 direct dependencies with version bounds (includes code-review-graph)
│
├── .gitignore                              # Excludes data/, .venv/, logs/, __pycache__/, .env, ngrok.exe
├── .env.example                            # Template: GITHUB_WEBHOOK_SECRET, CRG_SERVER_URL,
│                                           #          WORKSPACE_ROOT, METADATA_DB_PATH
│
├── AGENTS.md                               # Agent execution rules: domain_architect →
│                                           #     infra_engineer → phase1_reviewer
│                                           #     Async/sync boundary rules
│                                           #     Background process launch pattern (Windows)
│
├── PHASE_1.md                              # Full Phase 1 specification, tool parameter docs,
│                                           #     OOP vs functional style rules
│
├── OPENCODE.md                             # Status tracker, Definition of Done checklist,
│                                           #     changelog
│
└── PHASE_1_SUMMARY.md                      # This file
```

### Total: 40 Python files, 4 config/doc files, 2 Docker files

---

## 4. Database Schema

File: `data/phase1_metadata.db` (SQLite, synchronous engine)

```sql
-- Created by SQLModel.metadata.create_all() on startup
-- init_db() called from lifespan in main.py:14

CREATE TABLE repoworkspace (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id            VARCHAR NOT NULL,               -- e.g. "mohamedborhen/CLIP-DRDG"
    branch             VARCHAR NOT NULL,               -- branch this row tracks; default-branch row = base clone
    local_path         VARCHAR NOT NULL,               -- e.g. ".../data/workspaces/mohamedborhen_clip-drdg"
    last_synced_commit VARCHAR,                         -- SHA of last successfully built commit
    last_requested_at  DATETIME,                        -- recency signal for worktree-aware eviction (NULL on legacy rows)
    created_at         DATETIME NOT NULL,               -- Auto-set
    updated_at         DATETIME NOT NULL                -- Updated on each successful sync
);
-- One row per (repo_id, branch) — Branch-Aware addendum §7
CREATE UNIQUE INDEX ux_repoworkspace_repo_branch ON repoworkspace(repo_id, branch);
CREATE INDEX ix_repoworkspace_repo_id ON repoworkspace(repo_id);

CREATE TABLE graphsnapshot (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id            VARCHAR NOT NULL,               -- e.g. "mohamedborhen/CLIP-DRDG"
    commit_hash        VARCHAR NOT NULL,                -- SHA being built
    status             VARCHAR NOT NULL,                -- "ready", "error"
    error_message      VARCHAR,                         -- Error details on failure
    started_at         DATETIME NOT NULL,               -- Auto-set
    completed_at       DATETIME                         -- Set when build completes
);
CREATE INDEX ix_graphsnapshot_repo_id ON graphsnapshot(repo_id);
```

**Why two tables?**
- `repoworkspace` is the **registry**: tracks which repos are known, where they live on disk, and their last indexed commit (needed for incremental updates).
- `graphsnapshot` is the **audit log**: records every build attempt (success or failure). Without it, errors in background tasks would be invisible.

---

## 4b. Branch Handling (Branch-Aware addendum to Phase 2)

**Phase 1 built the base layer that only ever tracked one working tree per repo (the default branch).** The Branch-Aware addendum (specified in `Branch-Aware Graph Management.md`, built as part of Phase 2) extends this so the system can review **per-branch** code. The trigger model is **manual only**: a branch worktree and its graph are created or updated for exactly one reason — a user submits a `POST /review` for that `(repo_id, branch)` pair. UI branch selection has no side effect on its own.

### Schema change — one row per (repo_id, branch)

`repoworkspace` went from "one row per repo" to **one row per `(repo_id, branch)`**:

- Composite `UNIQUE(repo_id, branch)` replaces the old `repo_id UNIQUE`; a non-unique index on `repo_id` remains.
- New columns: `branch` and `last_requested_at` (recency signal for eviction; NULL for legacy rows → eviction falls back to `updated_at`).
- `db/engine.py` runs a real **4-step rebuild migration** (create `repoworkspace_new` → INSERT backfill → DROP → RENAME) — **not** a guarded `ALTER TABLE` — guarded on `branch` column presence, transactional, idempotent.
- Branch backfill is **deterministic**: `detect_branch` reads `git branch --show-current` first, then `git symbolic-ref refs/remotes/origin/HEAD` (default-branch fallback for the detached-HEAD case Phase 1's webhook `fetch+checkout` produces); raises rather than guessing. `last_requested_at` is derived from `updated_at`.
- `get_by_repo_id` is scoped to the default-branch row; `get_by_repo_id_and_branch` and `repo_is_registered` were added. `graphsnapshot` is unchanged — still commit-keyed, one row per build attempt.

### Worktree lifecycle

- **Paths (§12):** a worktree is a **sibling** of the base clone, still under `WORKSPACE_ROOT` (so the CRG server container sees it): base clone at `{root}/{safe_id}`, worktree at `{root}/{safe_id}__{safe_branch}` (`workspace_path_resolver.py` → `resolve_workspace_path` / `resolve_worktree_path`). No `CRG_DATA_DIR` override — worktree isolation is by filesystem path (verified against CRG docs before implementation).
- **Create (§3):** `GitRepoSource.create_worktree` runs `git fetch origin <branch>:<branch>` into the base clone first (a Phase 1 clone is shallow/`--depth 1`/single-branch, so the ref must be fetched or `git worktree add` fails), then `git worktree add <path> <branch>`; returns the checked-out HEAD sha.
- **Update (§3):** `update_worktree` runs `git fetch origin <branch>:refs/remotes/origin/<branch>` then `git reset --hard origin/<branch>` (fetch alone wouldn't update the checked-out files) and returns the new HEAD sha.
- **Orchestration (§5):** `EnsureBranchWorktreeService` (`application/repo_ingestion_service/ensure_branch_worktree.py`, sync, injected `RepoSourcePort` + `GraphBuilderPort` + a `WorkspaceStore` protocol):
  - **No row yet** → `create_worktree` + full `build()` (`full_rebuild=True`), then record `last_synced_commit` + a `GraphSnapshot`.
  - **Row exists but tip advanced** → `update_worktree` + incremental `update(base=old last_synced_commit)`; if that returns non-ready (e.g. force-push made the diff base unreachable), **fall back to a full `build()`**.
  - Releases the per-branch lock in a `finally`; errors are recorded as `GraphSnapshot(status="error")`.

### Trigger flow through `POST /review`

`POST /review` with `body.branch` set:
1. **Validate:** exactly one of `graph_commit_hash`/`branch` — both or neither → 400.
2. **Resolve branch → commit** live via the GitHub MCP `list_branches` tool (`infrastructure/mcp_clients/branch_resolution.py`, async Layer 5, `scoped()`-reduced to exactly `{list_branches}`, using `request.app.state.mcp_client`). Unknown branch → 404 `BranchNotFoundError`; unregistered repo → 404.
3. **Pre-flight:** `PrepareReviewContextService.execute(repo_id, resolved_commit, branch=branch)` returns the per-branch `local_path` or raises — 404 unregistered, 425 when the branch row is missing OR `last_synced_commit != resolved_commit` OR the graph isn't ready. It is **pure/side-effect-free** — it never triggers a build itself.
4. **On 425-with-branch:** the route dispatches `EnsureBranchWorktreeService.execute(...)` as a FastAPI `BackgroundTasks` task, then returns 425 immediately. A later `POST /review` for the same (repo, branch) at the resolved commit passes pre-flight.

> **D-11 fix (important):** the background task is attached via returning a `JSONResponse(status_code=425, ...)` with `response.background = background_tasks` set. `raise HTTPException(425)` silently **drops** the queued task (FastAPI only attaches `BackgroundTasks` on the normal return path) — verified against installed FastAPI source and live.

### When a graph actually updates (the exact rule)

- **Default branch (base clone):** auto-updates on every webhook push via `SyncOnWebhookService` (unchanged Phase 1 behavior). `process_webhook` is **branch-aware**: it only acts when the pushed branch equals the default-branch row's branch (`base.branch != branch` → no-op).
- **Non-default (worktree) branch:** updates **only when a user submits `POST /review` for that branch**, and only if the branch's remote tip has moved past what was last built (the 425 → `EnsureBranchWorktreeService`). A push to the branch is a **webhook no-op** — it does not update that branch's graph. Because `branch_resolution` resolves the *current remote tip*, the next review of the branch detects any advance and triggers the incremental update. If the branch is already current, submitting a review reuses the existing graph (no rebuild).

### Locks (§8) — branch-scoped

`acquire_workspace_lock(workspace_root, repo_id, branch=None)`: scope moved from `repo_id` to `(repo_id, branch)`. A branch lock file is `.{safe_id}_{safe_branch}.lock`; `branch=None` keeps the Phase 1 default key `.{safe_id}.lock` so existing registration call sites stay valid. `try_acquire_lock` (`timeout=0`) is a non-blocking probe the route uses to skip dispatch when another request is already building the branch.

### Webhooks (§6, §9) — branch-aware

- `process_webhook(repo_id, branch, commit_sha)` is a **no-op** for a push to any non-default (worktree) branch.
- `000…0` (branch deletion) is now a real **dispatch** to `cleanup_deleted_branch` (not an early return): it runs `git worktree remove` + `git worktree prune` in the base clone, deletes the per-branch `repoworkspace` row, and **leaves `graphsnapshot` rows** (they're commit-keyed and may back past audit rows). PR-closed is NOT a trigger.
- New read-only `GET /repos/{repo_id:path}/branches` proxies all remote branches (404 for unregistered repos). `{repo_id:path}` is required because `repo_id` is `owner/repo` (contains a slash).

### Eviction (§11) — worktree-aware

`WorkspaceEvictionService` orders rows by `last_requested_at` (fallback `updated_at`), resolves the base clone as the sibling `{root}/{sanitize_repo_id(repo_id)}`, and for a worktree uses `git worktree remove --force` + `git worktree prune` so the base clone's `.git/worktrees` metadata is cleaned (falling back to `shutil.rmtree` for a base clone or when the base is missing). `max_gb=10.0` default unchanged; wired to run once off the event loop in the lifespan. (The base-clone path is resolved deterministically — earlier a walk-up attempt could never reach the sibling base and caused `rmtree` to leave stale metadata; fixed in `_find_base_clone` and covered by unit tests.)

### Documented deviations (in `OPENCODE.md`)

- **D-8** — `RepoSourcePort` carries three new methods (`create_worktree`, `update_worktree`, `current_branch`); the spec names two — `current_branch` supports the migration backfill + `clone_repository` (a plain git read).
- **D-9** — the route wires a module-level `EnsureBranchWorktreeService` instance + `BackgroundTasks` instead of a spec-named module function; functionally equivalent composition root.
- **D-10** — branch identity for a non-default worktree row is the requested branch string (the worktree checkout fixes the commit); `last_synced_commit` records the built commit.
- **D-11** — see the 425 dispatch note above.

---

## 5. Libraries Used

| Library | Version Constraint | Role |
|---|---|---|
| **fastapi** | `>=0.100.0` | Web framework — route handlers, `BackgroundTasks`, request validation |
| **uvicorn** | `>=0.20.0` | ASGI server — serves the FastAPI app |
| **sqlmodel** | `>=0.0.16,<1` | ORM — synchronous SQLite engine, table models, query building |
| **mcp** | `>=1.27,<2` | MCP SDK — `streamable_http_client` + `ClientSession` for CRG communication |
| **filelock** | `>=3.0.0` | Cross-process file locking — serializes webhook processing per repo |
| **pydantic-settings** | `>=2.0.0` | Environment/config loading — reads `.env`, validates paths |
| **code-review-graph** | 2.3.7 (runtime) | Code knowledge graph — Tree-sitter parsing, graph DB, impact analysis |

**Why these and not alternatives:**
- **`subprocess.run(["git"])` instead of GitPython:** Avoids a heavy dependency for simple clone/fetch/checkout operations. Git is already ubiquitous.
- **`filelock.FileLock` instead of `asyncio.Lock`:** Works across multiple uvicorn workers (process-level), not just within one event loop.
- **`mcp` SDK instead of raw HTTP:** The `code-review-graph` server speaks the MCP protocol. Raw HTTP would require building JSON-RPC manually.

---

## 6. Configuration

File: `.env` (dev) or environment variables (production)

| Variable | Default | Resolved path | Purpose |
|---|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | `github-secret` | — | HMAC-SHA256 key for webhook payload verification |
| `CRG_SERVER_URL` | `http://localhost:5555/mcp` | — | CRG MCP server endpoint |
| `WORKSPACE_ROOT` | `./data/workspaces` | `{APP_ROOT}/data/workspaces` | Where cloned repos are stored |
| `METADATA_DB_PATH` | `./data/phase1_metadata.db` | `{APP_ROOT}/data/phase1_metadata.db` | SQLite database path |

**Path resolution:** The `model_validator` in `config.py` resolves all relative paths against `_APP_ROOT` (derived from `__file__`), NOT the current working directory. This ensures paths are consistent regardless of where `uvicorn` is launched from.

---

## 7. Webhook Request Lifecycle

### 7.1 Register a Repo (`POST /api/v1/repos`)

```
Client POST /api/v1/repos {repo_url, repo_id}
  │
  ├─ HTTP 400 if repo_url or repo_id missing
  ├─ background_tasks.add_task(register_and_build, repo_url, repo_id)
  └─ return {"status": "accepted", "repo_id": ...}

[Background thread - register_and_build()]:
  ├─ acquire_workspace_lock(workspace_root, repo_id)
  │   └─ Sanitize repo_id ("mohamedborhen/CLIP-DRDG" → "mohamedborhen_clip-drdg")
  │   └─ os.makedirs(..., exist_ok=True) — creates workspace dir
  │   └─ FileLock(/.{safe}.lock) — lock file OUTSIDE workspace dir
  ├─ with lock:
  │   ├─ CloneRepositoryService.execute()
  │   │   ├─ GitRepoSource.clone(repo_url, local_path)
  │   │   │   ├─ Path.parent.mkdir(exist_ok=True) — ensure parent exists
  │   │   │   ├─ shutil.rmtree(target_path) — clean stale directories
  │   │   │   ├─ git clone --depth 1 <url> <target_path>
  │   │   │   └─ git rev-parse HEAD → commit_sha
  │   │   └─ CRGMcpAdapter.build(repo_root=local_path)
  │   │       └─ asyncio.run(_call_crg_async(...))
  │   │           └─ streamable_http_client → ClientSession.initialize()
  │   │           └─ session.call_tool("build_or_update_graph_tool",
  │   │               {repo_root, full_rebuild=True})
  │   │           └─ if result.isError → raise CRGToolError
  │   │               else → GraphBuildStatus(status="ready")
  │   ├─ try/except around execute() → errors saved as snapshots
  │   └─ Session(engine):
  │       ├─ RepoWorkspace.insert(repo_id, local_path, commit_sha)
  │       └─ GraphSnapshot.insert(repo_id, commit_hash, status)
  │       └─ session.commit()
```

### 7.2 Process a Push Webhook (`POST /api/v1/webhook`)

```
GitHub POST /api/v1/webhook
  │
  ├─ request.body() → raw_body (bytes) — SAVE BEFORE parsing
  ├─ X-Hub-Signature-256 header
  ├─ verify_signature(raw_body, header, github_webhook_secret)
  │   └─ hmac.new(secret, raw_body, sha256).hexdigest() == signature
  │   └─ If bad → HTTP 403 — reject BEFORE any processing
  ├─ json.loads(raw_body)
  ├─ payload["after"]
  │   └─ If "0000000000000000000000000000000000000000" → branch deletion → skip
  ├─ background_tasks.add_task(process_webhook, repo_id, sha)
  └─ return {"status": "accepted"}  ← HTTP response sent immediately

[Background thread - process_webhook()]:
  ├─ Session(engine) → SELECT * FROM repoworkspace WHERE repo_id = ?
  │   └─ If None → log warning, return (untracked repo)
  ├─ Branch-aware (Branch-Aware §6): if pushed branch != default-branch row's branch → no-op
  │   (non-default/worktree branch pushes never auto-sync — they update only via POST /review)
  ├─ acquire_workspace_lock(workspace_root, repo_id)
  ├─ with lock:
  │   ├─ SyncOnWebhookService.execute()
  │   │   ├─ GitRepoSource.sync(local_path, ref)
  │   │   │   ├─ git fetch origin <ref>
  │   │   │   ├─ git checkout <ref>
  │   │   │   └─ git rev-parse HEAD → commit_sha
  │   │   └─ CRGMcpAdapter.update(repo_root, base=last_indexed_commit)
  │   │       └─ asyncio.run(_call_crg_async(...))
  │   │           └─ session.call_tool("build_or_update_graph_tool",
  │   │               {repo_root, full_rebuild=False, base=...})
  │   ├─ try/except → status/error_message
  │   ├─ GraphSnapshot.insert(repo_id, commit_hash, status, error_message)
  │   ├─ If status=="ready":
  │   │   ├─ UPDATE repoworkspace SET last_synced_commit=sha, updated_at=NOW()
  │   │   └─ session.commit()
```

---

## 8. Security

### Signature Verification (Critical — Done Correctly)

```python
raw_body = await request.body()            # 1. Read raw bytes
signature = request.headers.get(...)       # 2. Get signature header
if not verify_signature(raw_body, ...):    # 3. Verify BEFORE parsing
    raise HTTPException(403)

payload = json.loads(raw_body)             # 4. Parse JSON ONLY after verification
background_tasks.add_task(...)             # 5. Schedule work AFTER verification
```

**Security property:** Unverified payloads are never queued, even momentarily. This is the only acceptable ordering for production webhook processing.

### Secrets Management

- `.env` files are **gitignored** — never committed to version control
- `.env.example` provides a template with placeholder values (`your-secret-here`)
- Docker Compose loads secrets via `env_file: .env` (not hardcoded in compose file)
- In Docker, secrets are injected at container runtime

---

## 9. Error Handling Strategy

| Error source | Where detected | How handled | DB impact |
|---|---|---|---|
| Git clone/fetch fails | `_run_git()` → `RuntimeError(stderr)` | Caught by `try/except` in webhooks.py | `GraphSnapshot(status="error", error_message=stderr)` |
| Git checkout (ref not found) | `_run_git()` → `RuntimeError(stderr)` | Caught by `try/except` in webhooks.py | `GraphSnapshot(status="error")` |
| CRG transport failure (connection refused, timeout) | `_call_crg()` retry loop | 3 attempts with 1s, 2s, 4s backoff. After 3 failures: return `GraphBuildStatus(status="error")` | `GraphSnapshot(status="error")` |
| CRG tool reports failure (`isError=true`) | `_call_crg_async()` → raise `CRGToolError` | Caught in `_call_crg()` → return `GraphBuildStatus(status="error", error_message=content)` | `GraphSnapshot(status="error")` |
| Filesystem errors (disk full, permissions) | Propagates as `OSError` / `PermissionError` | Caught by top-level `except Exception` in webhooks.py | `GraphSnapshot(status="error", error_message=str(e))` |
| Lock acquisition timeout | `FileLock(timeout=5)` → `TimeoutError` | Propagates to caller — no lock, no processing | No snapshot created (repo is busy) |

---

## 10. Concurrency Model

```
┌─────────────────────────────────────────────────────────────────┐
│ Uvicorn Worker 1           Uvicorn Worker 2                     │
│ ┌────────────────────┐    ┌────────────────────┐                │
│ │ process_webhook(A) │    │ process_webhook(A) │                │
│ │ acquire_lock(A)    │    │ acquire_lock(A)    │                │
│ │   ┌──────────────┐ │    │   ┌──────────────┐ │                │
│ │   │ LOCK HELD   │ │    │   │ WAITING     │ │                │
│ │   │ git fetch   │ │    │   │ (timeout 5s)│ │                │
│ │   │ CRG update  │ │    │   │ ──────────→ │ │                │
│ │   │ DB write    │ │    │   │ git fetch   │ │                │
│ │   │ release()   │ │    │   │ CRG update  │ │                │
│ │   └──────────────┘ │    │   │ DB write    │ │                │
│ └────────────────────┘    └────────────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

**Key points:**
- `filelock.FileLock` is process-level, not event-loop-level — works across multiple uvicorn workers.
- Lock file is placed **outside** the workspace directory (`/.{safe}.lock`) to avoid Windows `PermissionError` when `shutil.rmtree` runs inside the lock.
- Timeout of 5 seconds prevents deadlocks. If a lock can't be acquired, the webhook silently skips (next push will catch up).

---

## 11. Docker Deployment

### docker-compose.yaml

```yaml
services:
  code-review-agent:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    environment:
      - CRG_SERVER_URL=http://crg-server:5555/mcp
    volumes:
      - workspace_data:/app/data        # ← Named volume (NOT bind mount)
    depends_on:
      crg-server:
        condition: service_healthy

  crg-server:
    build:
      context: .
      dockerfile: Dockerfile.crg
    command: code-review-graph serve --http --port 5555 --host 0.0.0.0
    expose: ["5555"]                     # Internal only; not exposed to host
    volumes:
      - workspace_data:/app/data        # ← Shared named volume
    working_dir: /app
    healthcheck:
      test: python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('localhost',5555))"
      interval: 2s
      timeout: 3s
      retries: 5
      start_period: 60s

volumes:
  workspace_data:                        # ← Persistent named volume
```

**Design decisions:**
- **Named volume (`workspace_data`) instead of bind mount:** SQLite is unsafe on NFS-style network mounts. A named Docker volume ensures local filesystem semantics.
- **Shared volume between containers:** Both the FastAPI app and the CRG server need access to the same workspace files and SQLite database.
- **`depends_on` with `condition: service_healthy`:** The app container waits until the CRG server's TCP healthcheck passes, not just until the container starts. This prevents startup race conditions.
- **`CRG_SERVER_URL` explicitly overridden:** In Docker the CRG server is reachable at `http://crg-server:5555/mcp` (via Docker DNS), not the default `localhost:5555/mcp`.
- **Port 5555 not exposed to host:** The CRG server is only reachable within the Docker network, reducing the attack surface.
- **Separate Dockerfile.crg:** CRG server has its own build stage (`Dockerfile.crg`) that installs all Python deps including `code-review-graph` from `requirements.txt`, avoiding runtime pip install on every container start and eliminating the startup delay.

### Dockerfile (code-review-agent)

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/src/code_review_agent/ ./
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Dockerfile.crg (crg-server)

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["code-review-graph", "serve", "--http", "--port", "5555", "--host", "0.0.0.0"]
```

---

## 12. Comparison: Original Plan vs Implementation

| Requirement | Status | Notes |
|---|---|---|
| Domain layer with ZERO infra imports | ✅ | `entities/` and `ports/` import only stdlib + typing |
| Synchronous Application layer | ✅ | `def execute()`, not `async def` |
| Only `asyncio` in `crg_mcp_adapter.py` | ✅ | Single `asyncio.run()` call |
| HMAC verification before `add_task` | ✅ | `verify_signature()` on raw body bytes before queuing |
| Branch deletion detection (000...) | ✅ | Returns `{"status": "skipped"}` |
| `BackgroundTasks` for slow work | ✅ | Both clone+graph and sync+update run deferred |
| `filelock` for per-repo concurrency | ✅ | Lock outside workspace dir to avoid Windows issues |
| `build_or_update_graph_tool` only | ✅ | No other CRG tools called |
| `full_rebuild=true` first, `false` for updates | ✅ | `build()` vs `update()` pass appropriate flags |
| `repo_root` always passed explicitly | ✅ | Never left to auto-detect |
| Retry 3x exponential backoff | ✅ | Transport errors only; tool errors surfaced immediately |
| Error handling with DB persistence | ✅ | `try/except` → `GraphSnapshot(status="error")` |
| Docker named volume | ✅ | `workspace_data:` named volume |
| `requirements.txt` with version bounds | ✅ | 7 direct dependencies (code-review-graph included) |
| `.gitignore` for sensitive files | ✅ | `.env`, `data/`, `.venv/`, `logs/`, binaries |
| Git clone stderr exposed | ✅ | `_run_git` raises `RuntimeError(stderr)` |
| Stale directory cleanup before clone | ✅ | `shutil.rmtree(target_path)` inside lock |
| Upsert for re-registering same repo | ✅ | `register_and_build` checks existing row before INSERT; avoids UNIQUE constraint crash |
| Workspace eviction (LRU) | ✅ | Worktree-aware, wired to lifespan (Branch-Aware §11); code complete |
| Branch-aware webhooks (§6/§9) | ✅ | `process_webhook` no-ops non-default branch pushes; `000…0` → real cleanup dispatch; `GET /repos/{repo_id}/branches` read-only proxy |
| Per-branch review (`POST /review` + branch) | ✅ | Resolve branch→commit via GitHub `list_branches` (404 unknown), 425 → background `EnsureBranchWorktreeService` (D-11 JSONResponse fix) |
| `RepoWorkspace` per (repo_id, branch) | ✅ | `UNIQUE(repo_id, branch)`, 4-step rebuild migration, deterministic branch backfill |
| Worktree lifecycle | ✅ | `create_worktree` (fetch-then-add, shallow-clone fix), `update_worktree` (fetch + reset --hard), full-rebuild fallback on force-push base-unreachable |
| Per-branch locks (§8) | ✅ | `acquire_workspace_lock(branch=None)`, `.{safe}_{safe_branch}.lock`, `try_acquire_lock` probe |

---

## 13. How to Test (Quick Reference)

### Server Startup
```powershell
# backend/src/code_review_agent/
$env:PYTHONPATH = "."
$proc = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m uvicorn main:app --host 127.0.0.1 --port 8000" -PassThru -RedirectStandardOutput "..\..\..\logs\uvicorn.stdout.log" -RedirectStandardError "..\..\..\logs\uvicorn.stderr.log"
Start-Sleep -Seconds 5
Invoke-RestMethod -Uri http://127.0.0.1:8000/docs -Method Get
```

### Register Repo
```powershell
$body = @{repo_url="https://github.com/owner/repo.git"; repo_id="owner/repo"} | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/repos -Method Post -Body $body -ContentType "application/json"
```

### Check Status
```powershell
.\.venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, 'backend/src/code_review_agent')
from sqlmodel import Session, select
from infrastructure.db.engine import engine
from infrastructure.db.models import RepoWorkspace, GraphSnapshot
with Session(engine) as s:
    for w in s.exec(select(RepoWorkspace)).all():
        print(f'{w.repo_id} last_commit={w.last_synced_commit[:12]}')
    for snap in s.exec(select(GraphSnapshot)).all():
        print(f'{snap.repo_id} {snap.commit_hash[:12]} {snap.status}')
"
```

### Simulate Webhook
```powershell
$sha = .\.venv\Scripts\python.exe -c "
import subprocess; r=subprocess.run(['git','rev-parse','HEAD'],
    cwd='backend/src/code_review_agent/data/workspaces/{safe_id}',
    capture_output=True,text=True); print(r.stdout.strip())"
$payload = @{after=$sha; repository=@{full_name="owner/repo"}} | ConvertTo-Json
$hmac = .\.venv\Scripts\python.exe -c "import hmac,hashlib; print('sha256='+hmac.new(b'github-secret','$($payload)'.encode(),hashlib.sha256).hexdigest())"
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/webhook -Method Post -Body $payload -ContentType "application/json" -Headers @{"X-Hub-Signature-256"=$hmac}
```

### Real Webhook (ngrok)
```powershell
.\ngrok.exe http 8000
# → https://xxxx.ngrok-free.dev/api/v1/webhook
# Configure in GitHub repo → Settings → Webhooks → Add webhook
```

### Security Tests
```powershell
# Bad signature → 403
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/webhook -Method Post -Body '{}' -ContentType "application/json" -Headers @{"X-Hub-Signature-256"="bad"}

# Branch deletion → skipped
$del = @{after="0000000000000000000000000000000000000000"; repository=@{full_name="owner/repo"}} | ConvertTo-Json
$sig = .\.venv\Scripts\python.exe -c "import hmac,hashlib; print('sha256='+hmac.new(b'github-secret','$($del)'.encode(),hashlib.sha256).hexdigest())"
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/webhook -Method Post -Body $del -ContentType "application/json" -Headers @{"X-Hub-Signature-256"=$sig}
```

---

## 14. Known Technical Debt (Accepted for Phase 1)

| Item | Impact | When to fix |
|---|---|---|
| `BackgroundTasks` have no persistence | If the process crashes between webhook ack and task completion, the update is silently lost | Phase 2+ with a proper task queue (Celery/Redis) |
| `SyncOnWebhookService.execute()` base defaults to `HEAD~1` if `last_indexed_commit` is None | Safe but may re-parse the most recent commit unnecessarily | Phase 2 when first-commit edge cases are handled |
| No API key for `POST /repos` | Anyone who can reach the endpoint can register repos | Phase 2 with auth middleware |
| `graphsnapshot.started_at` uses `datetime.utcnow()` (deprecated) in SQLModel field defaults | Works but produces deprecation warning in Python 3.12+ | Next maintenance pass |