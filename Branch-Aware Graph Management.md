# Branch-Aware Graph Management

**Status:** Phases 1 and 2 are complete and implemented (not just planned — verified against `PHASE_1_SUMMARY.md` and the current `PHASE_2.md`). This is an addendum. It names exact existing classes, ports, and services from both phases so the changes below are precise edits to real code, not new freestanding logic.

**This touches Phase 1 and Phase 2 foundations while Phase 2 work is still in flight.** `OPENCODE.md`'s current focus is elsewhere (multi-provider model selection, compliance tools) — nothing branch-related has started yet. Implement carefully enough not to collide with that in-progress work. Per `AGENTS.md`, Phase 1 code is only modified where this document explicitly says so, and any Phase 1 blocker found during this work is logged in `OPENCODE.md`, not silently "fixed."

## 0. Rules for implementing this doc

*   **Do not guess.** Anywhere this doc says "NEEDS VERIFICATION," stop and check — via Context7, the library's own docs, or the actual current source — before writing that piece.
*   **Do not invent numbers.** §11's eviction thresholds already exist in code (`workspace_eviction_service.py`, default `max_gb=10.0`, LRU by `updated_at` ascending) — read them, don't invent new ones.
*   **No frontend work** — see §10.
*   Read §13 before writing any code.

## 1. Problem

Multiple branches need to be reviewable without re-cloning per branch, and without building a graph for any branch nobody asked about.

## 2. Trigger model — manual only

**A worktree and its graph are created or updated for exactly one reason: a user explicitly submitted a review request for that (repo, branch) pair — `POST /review`.** Selecting a branch in a UI dropdown has no side effect by itself; only submitting does.

**No automatic *relevance* detection.** A `push` event does not create or update a worktree, and does not check for an open PR or default-branch status. This addendum does not add a `pull_request` webhook listener.

**Non-zero push payloads are ignored by this addendum**, but Phase 1's existing sync behavior must be preserved for the default branch: the webhook handler must become branch-aware (match `payload["ref"]` to a `RepoWorkspace` row) so that a push to the default-branch row keeps Phase 1's existing `process_webhook` sync, while a push to a worktree row is a no-op (worktrees update only via `POST /review`).

**Branch deletion is the one exception, and it's not new** — it's Phase 1's existing detection mechanism, reused for cleanup: a `push` event where `after == "0000000000000000000000000000000000000000"` (confirmed in `PHASE_1_SUMMARY.md` §7.2 and its own test in §13). §9 uses this exact check.

⚠️ **Real compatibility risk, not a "confirm later" item — two concrete code changes:**

1. **The `000...0` early-return must become a dispatch.** `infrastructure/api/routes/webhooks.py:35-36` currently `return {"status": "skipped", "reason": "branch deletion"}` *before* any background task is added. §9's cleanup requires converting that early-return into a `background_tasks.add_task(...)` dispatch (parsing the branch from `payload["ref"]`), not a plain skip.
2. **`process_webhook`'s row lookup becomes ambiguous.** It currently does `select(RepoWorkspace).where(repo_id == repo_id)` expecting exactly one row (`webhooks.py:53-58`). Once `RepoWorkspace` has multiple rows per `repo_id` (§7), this must query by `(repo_id, branch)` from `payload["ref"]`.

## 3. Core mechanism — confirmed

**No re-clone:** one base clone per repo. Additional branches are added via `git worktree add`, sharing the base clone's object database.

⚠️ **NEEDS VERIFICATION (CRG isolation):** Use Context7 to inspect the `code-review-graph` library's actual behavior regarding data directories *before* implementing the worktree logic. We assume Git worktrees are treated as individual roots with their own `.code-review-graph/` defaults, but if the library actually requires `CRG_DATA_DIR` to ensure isolation, §12 must be updated to dynamically set that environment variable per background task.

**`RepoSourcePort` (`domain/repo/repo_source_port.py`, currently only `clone()` + `sync()`) gains two methods**, implemented by `GitRepoSource` in Layer 5 (`infrastructure/repo_source/git_repo_source.py`):

```python
def create_worktree(self, base_repo_path: str, branch: str, target_path: str) -> str: ...  # returns commit sha
def update_worktree(self, worktree_path: str, branch: str) -> str: ...                     # returns commit sha
```

**Shallow Clone Fix:** Phase 1's `clone()` uses `git clone --depth 1` (`git_repo_source.py:28`). A depth-1 clone contains exactly one branch's tip, so `git worktree add` for any other branch will fail with "no such ref." Either:

1. Remove `--depth 1` from the base `clone()` to fetch all branches, or
2. Add a pre-requisite step in `create_worktree`: `git fetch origin <branch>:<branch>` before creating the worktree.

**`create_worktree` (option 2):**

```bash
git fetch origin <branch>:<branch>
git worktree add <target_path> <branch>
git rev-parse HEAD        # run in <target_path>
```

**`update_worktree` implements the two-step sequence Phase 1's plain `sync()` (`git fetch + git checkout`) doesn't need:**

```bash
git fetch origin <branch>
git reset --hard origin/<branch>
git rev-parse HEAD
```

`git fetch` alone only updates the remote-tracking ref; it does not update files already checked out in an existing worktree. `reset --hard` is used instead of `checkout` because this path is fully automated and guarantees a clean state even if a previous build left stray files.

**Graph build** (via `GraphBuilderPort`, implemented by `CRGMcpAdapter` calling `build_or_update_graph_tool` with `repo_root`/`full_rebuild`/`base`):

```python
full_rebuild: bool = False   # True only on a worktree's first build
base: str                    # RepoWorkspace.last_synced_commit for this branch
```

`base` comes from what the system recorded last time (`last_synced_commit`), diffed against the freshly-resolved branch head (§4). **Force-push safety:** if diffing against `base` fails because that commit is no longer reachable, catch it and fall back to `full_rebuild=True`.

## 4. Branch → commit resolution

Resolve a branch name to its current commit SHA via the GitHub MCP server's `list_branches` tool. This is an **async** call and must live in the **Infrastructure layer (Layer 5)** — e.g. a new `infrastructure/mcp_clients/branch_resolution.py`, modeled on `CRGMcpAdapter`.

**Strict Tool Invocation Rule (AGENTS.md compliance):** `MultiServerMCPClient.get_tools()` has **no name-filter parameter** — it returns the full tool list for a server, and there is no per-name getter. Do not invent a `get_tools(tool_names=...)` or `get_tool_by_name(...)` API. The compliant, implementable pattern is fetch-then-reduce using the existing `scoped()` helper (`infrastructure/mcp_clients/mcp_client_factory.py:60`), exactly as `tool_scoping.py:170-174` already does:

```python
# infrastructure/mcp_clients/branch_resolution.py (Layer 5)
async def resolve_branch_to_commit(mcp_client, owner: str, repo: str, branch: str) -> str:
    github_tools = await mcp_client.get_tools(server_name="github")
    list_branches_tool = scoped(github_tools, {"list_branches"})[0]
    result = await list_branches_tool.ainvoke({"owner": owner, "repo": repo})
    # NEEDS VERIFICATION: exact list_branches response shape — expect a list of
    # branch objects each carrying a commit SHA; find the entry matching `branch`.
    ...
```

The full registry list is reduced immediately and is never handed to any agent.

**FastAPI State Management:** when invoked from the FastAPI route, the MCP client is accessed strictly via `request.app.state.mcp_client` (mandated by PHASE_2.md). Do not instantiate a new client per request.

⚠️ **NEEDS VERIFICATION:** only the exact `list_branches` tool name and its response shape — confirm via `mcpcurl tools --help` or Context7 before hardcoding, per PHASE_2.md's established practice for the GitHub tool registry. The `X-MCP-Toolsets` header already includes `repos` (`mcp_client_factory.py:40`), so no server-config change is expected.

## 5. Full workflow

**Route (`POST /review`, `infrastructure/api/routes/review.py`):**

1. Validate that exactly one of `branch` or `graph_commit_hash` is supplied (400 on both/neither) — see §6.
2. `branch` supplied instead of `graph_commit_hash`?
   → `resolved_commit = await resolve_branch_to_commit(request.app.state.mcp_client, owner, repo, branch)` (§4)
   else (existing programmatic/CI path, unchanged):
   → `resolved_commit = body.graph_commit_hash; branch = None`
3. Resolve `repo_root` via `PrepareReviewContextService` — keep the existing synchronous call style (currently `review.py:71`, the documented blessed sync exception in AGENTS.md/PHASE_2.md; do not mix in `asyncio.to_thread` unless the whole file adopts it):
   ```python
   repo_root = _prepare_context.execute(body.repo_id, resolved_commit, branch=branch)
   ```
4. On `GraphNotReadyError`, **only when `branch` was supplied** (the plain `graph_commit_hash` path keeps Phase 2's existing wait-and-425 behavior):
   ```python
   if try_acquire_lock(settings.workspace_root, repo_id, branch):   # non-blocking, timeout=0
       background_tasks.add_task(ensure_branch_worktree_and_graph,
                                 repo_id, branch, resolved_commit)
       # the task releases this same lock in a finally block, success or failure
   # if the lock is not acquired, another request is already building this branch —
   # do nothing further, just fall through to the 425
   return 425
   ```
   **The route must gain a `background_tasks: BackgroundTasks` parameter** (current signature is `async def review(request: Request, body: ReviewRequest)` — `webhooks.py:25` already shows the pattern).
5. On success: proceed with the existing review pipeline using `repo_root`, unchanged. `ReviewSession.graph_commit_hash` and `AgentInput.graph_commit_hash` store `resolved_commit` in both paths — no change to `ReviewSession` (out of scope per §14).

The lock does double duty: per-branch concurrency guard (§8) and, via its non-blocking try, the signal for "is a build already running for this branch." No new DB status column is needed.

**`ensure_branch_worktree_and_graph` belongs in the Application layer** — not inside `review.py`. Add a new service `application/repo_ingestion_service/ensure_branch_worktree.py` alongside the existing `CloneRepositoryService`/`SyncOnWebhookService`, with the same shape: a class with a sync `execute()` method that orchestrates `RepoSourcePort.create_worktree`/`update_worktree` (§3) and `GraphBuilderPort.build`/`update`, updates `RepoWorkspace.last_synced_commit`/`GraphSnapshot` on completion, and releases the lock in a `finally` block.

**`execute()` (Layer 3, `application/review_service/prepare_review_context.py`) gains `branch` as a trailing optional kwarg** — existing call sites stay valid unchanged:

```python
def execute(self, repo_id: str, graph_commit_hash: str,
            branch: str | None = None) -> str:
    if not self._workspace_query.repo_is_registered(repo_id):        # NEW port method
        raise RepoNotFoundError(repo_id)                               # -> 404: never POST /repos'd
    if branch is not None:
        workspace = self._workspace_query.get_by_repo_id_and_branch(repo_id, branch)  # NEW
    else:
        workspace = self._workspace_query.get_by_repo_id(repo_id)      # existing method, scoped to the default-branch row (see §7)
    if workspace is None or workspace.last_synced_commit != graph_commit_hash:
        raise GraphNotReadyError(repo_id, graph_commit_hash)           # -> 425, now also "branch not built yet"
    if not self._readiness.is_ready(repo_id, graph_commit_hash):
        raise GraphNotReadyError(repo_id, graph_commit_hash)
    return workspace.local_path
```

`execute()` stays pure and side-effect-free — it does **not** trigger a build. Step 4 is what does. The 404/425 split is an intentional API upgrade distinguishing "unregistered repo" from "registered repo, branch not built yet."

## 6. API surface changes

**`ReviewRequest` (`infrastructure/api/models.py`) — additive change:**

```python
class ReviewRequest(BaseModel):
    repo_id: str
    graph_commit_hash: str | None = None   # now optional
    branch: str | None = None              # NEW
    request_type: str
    diff_content: str | None = None
    question: str | None = None
```

**Exactly one** of `branch` or `graph_commit_hash` must be provided — reject a request supplying both or neither (400).

**New read-only endpoint, backend only:** `GET /repos/{repo_id}/branches`, added to `infrastructure/api/routes/webhooks.py` (where `POST /repos` registration already lives). It proxies `resolve_branch_to_commit`'s tool for all branches — same read-only GitHub scoping already in place, no new auth or write capability.

## 7. Database schema changes

**`repoworkspace` — becomes per-branch, not per-repo.**

* **Migration, not just an addition — `ALTER TABLE` cannot do this.** SQLite supports no constraint changes via `ALTER TABLE`. Use the standard 4-step rebuild, inside a transaction:
  1. `CREATE TABLE repoworkspace_new (...)` with `UNIQUE(repo_id, branch)` instead of `repo_id UNIQUE`.
  2. `INSERT INTO repoworkspace_new SELECT ... FROM repoworkspace` (backfill `branch` and `last_requested_at` — below).
  3. `DROP TABLE repoworkspace`.
  4. `ALTER TABLE repoworkspace_new RENAME TO repoworkspace`.
* **Deterministic branch backfill:** existing rows predate branch-awareness. Do not guess or hardcode a default like "main." Each row's `local_path` points at a real Phase 1 clone — read the branch via `git branch --show-current` (or `git symbolic-ref HEAD`) at that `local_path` and write that exact value into the new `branch` column.
* **Timestamp backfill:** populate the new `last_requested_at` column from the existing row's `updated_at`. Moving forward, use `datetime.now(timezone.utc)` (matching `db/models.py`'s existing timezone-aware fields — do not propagate Phase 1's deprecated naive `datetime.utcnow()`).
* **Add `branch: str`** and **`last_requested_at: datetime`** (for §11's eviction). `local_path` now points at that branch's worktree directory. Keep the field name `last_synced_commit` (matches Phase 1 — don't introduce a second name).
* **The domain entity `domain/entities/repo_workspace.py` (dataclass) gains `branch` too** — the DB layer is not enough; `SQLModelRepoWorkspaceRepository` maps DB → entity (`repo_workspace_repository.py:22-28`) and must carry the new field. Three files change: the table, the dataclass, and the repository mapping.

**`RepoWorkspaceQueryPort` (`domain/review/review_context_ports.py`) gains:**

```python
def repo_is_registered(self, repo_id: str) -> bool: ...              # NEW
def get_by_repo_id_and_branch(self, repo_id: str, branch: str) -> RepoWorkspace | None: ...  # NEW
```

**Concrete implementation is mandatory:** implement both methods' SQL in `infrastructure/db/repo_workspace_repository.py` (`SQLModelRepoWorkspaceRepository`). A Protocol change alone will cause runtime failures.

**`get_by_repo_id` stays, but is deliberately scoped:** with multiple rows per `repo_id`, a bare `WHERE repo_id = ?` is ambiguous. Scope it explicitly to the designated default-branch row (e.g. `WHERE repo_id = ? AND branch = <default_branch>`) — a deliberate decision, not "whichever row the query happens to return first."

**`graphsnapshot` — no structural change.** Already keyed by `(repo_id, commit_hash)`; stays valid regardless of which branch built it. Don't delete these on branch cleanup (§9).

**There is no `GraphBuildStatus` table to change** — it's a domain dataclass (`domain/entities/graph_build_status.py`), an in-memory return type from `GraphBuilderPort`, never persisted on its own.

**No new tables.**

## 8. `filelock` changes

Lock scope moves from `repo_id` to `(repo_id, branch)`. Reuse `sanitize_repo_id` (`workspace_path_resolver.py:4` / `workspace_lock.py:7`) for branch names too.

* **Lock file naming convention:** `f".{sanitize_repo_id(repo_id)}_{sanitize_repo_id(branch)}.lock"` — the leading dot matches Phase 1's existing hidden-lock convention (`workspace_lock.py:15`), and the lock file lives in `workspace_root` (not inside the worktree dir, which may not exist yet).
* **`acquire_workspace_lock` (existing, used by `webhooks.py:60` and `webhooks.py:110`) gains `branch: str | None = None`** — defaulting to the default-branch key so existing call sites stay valid, and so the webhook default-branch path locks correctly alongside worktree locks.
* **New non-blocking API in `workspace_lock.py`:** `try_acquire_lock(workspace_root, repo_id, branch) -> bool` — acquire the per-branch lock with `timeout=0`, returning `True` on immediate acquisition and `False` on `filelock.Timeout`.
* **Blocking execution:** the background task (`ensure_branch_worktree_and_graph`) acquires the same lock blocking with Phase 1's existing 5s timeout and releases it in a `finally` — same discipline as Phase 1's existing `process_webhook`/`register_and_build`.

## 9. Branch deletion — cleanup

Uses Phase 1's existing detection mechanism — a push event with `after` equal to the all-zero SHA. On detected deletion for `(repo_id, branch)`, dispatched from the webhook handler (§2):

1. `git worktree remove <path>`, then `git worktree prune`.
2. Delete the `RepoWorkspace` row for `(repo_id, branch)`.
3. Leave `GraphSnapshot` rows alone — commit-keyed, may still back past `AgentExecution` audit rows.

**PR-closed is not a cleanup trigger** — branch deletion is the only one.

## 10. Frontend boundary — read before building anything UI-related

| In scope now (backend) | Out of scope (frontend, future phase) |
| --- | --- |
| `ReviewRequest.branch` + resolution logic (§6) | The actual dropdown component |
| `GET /repos/{repo_id}/branches` (§6) | Any UI state, routing, or rendering |
| Everything in §3–§9 | Anything under a `frontend/`/`ui/` directory |

Do not build any frontend code as part of this addendum. The backend pieces above are fully testable via `POST /review` / `GET /repos/{repo_id}/branches` directly.

## 11. Worktree eviction — extend the existing service

`infrastructure/workspace/workspace_eviction_service.py` already exists — `WorkspaceEvictionService(workspace_root, max_gb=10.0)`, LRU eviction ordering `RepoWorkspace` by `updated_at.asc()`, described as "code complete, not yet wired" (`PHASE_1_SUMMARY.md` §3/§14). This is not a net-new feature. Two things:

1. **Make it worktree-aware** — evict per-branch rows using `last_requested_at` (§7) as the recency signal, instead of (or in addition to) `updated_at`. Read the actual current logic before extending; do not invent new thresholds alongside the existing ones.
2. **Wire it to a background task** — it currently isn't, for anything.

## 12. Config

| Setting | This pass | Why |
| --- | --- | --- |
| `CRG_DATA_DIR` | Not set by default, **but** if §3's Context7 verification reveals the library requires it for worktree isolation, update this to dynamically set the environment variable per background task. | See §3. |
| Worktree base path | Inside the existing `WORKSPACE_ROOT` (`workspace_data` Docker volume) | Both containers only share that one mount (`docker-compose.yaml`) — a separate path wouldn't be visible to the CRG server container. |
| Lock key scheme | `f".{sanitize_repo_id(repo_id)}_{sanitize_repo_id(branch)}.lock"` in `WORKSPACE_ROOT` | §8. |

## 13. Pre-Implementation Verification Checklist

- [ ] Verify the exact `list_branches` tool name and response shape via `mcpcurl tools --help` or Context7 **before** writing the adapter code (§4).
- [ ] Use Context7 to inspect the `code-review-graph` library's actual data-directory behavior before implementing the worktree logic, to confirm isolation (or update §12 for `CRG_DATA_DIR`) (§3).
- [ ] Verify the `repoworkspace` migration uses the 4-step table rebuild procedure (create/insert/drop/rename), not a guarded `ALTER TABLE` (§7).
- [ ] Ensure deterministic branch backfill via `git branch --show-current` executed at each existing `local_path`, and `last_requested_at` backfilled from `updated_at` (§7).
- [ ] Update `RepoWorkspaceQueryPort` **and** implement both new methods in `SQLModelRepoWorkspaceRepository`, plus add `branch` to the domain entity and repository mapping (§7).
- [ ] Verify `resolve_branch_to_commit` is implemented in Layer 5, uses `request.app.state.mcp_client`, and reduces the `get_tools()` output via `scoped()` rather than granting/unfiltered fetching (§4).
- [ ] Read `workspace_eviction_service.py`'s actual current logic/thresholds before extending (§11).
- [ ] Convert the webhook's `000...0` early-return into a cleanup dispatch and make `process_webhook`'s lookup branch-aware (§2, §9).
- [ ] Add the `BackgroundTasks` parameter to the `POST /review` route signature (§5).

## 14. Explicitly out of scope for this pass

* Any frontend/UI code (§10).
* PR-closed as a cleanup trigger.
* Any change to `AgentExecution`/`ReviewSession` or the review pipeline itself — this doc only touches ingestion/graph management.
Key changes from your version: §4 now uses the real fetch-then-scoped() pattern (no invented API), §5 adds the route BackgroundTasks param and states the resolved_commit behavior, §7 adds the domain-entity + repository-mapping files and the explicit get_by_repo_id default-branch scoping decision, §2/§9 call out the 000...0 early-return conversion, §8 adds acquire_workspace_lock's branch param and the hidden-dot lock naming. The two NEEDS VERIFICATION items (GitHub list_branches shape, CRG data-dir behavior) are preserved as explicit stop-and-check gates.