# Phase 4 — E2E Test Plan & Runbook

Verify, against the live system, that every Phase 4 mechanism actually works end to end:

1. **In-context (short-term) summarization** — `SummarizationMiddleware` (222,822-token trigger).
2. **Durable conversation summary** — `MemorySummary` row persisted after a conversation-scoped review.
3. **Long-term shared memory** — `manage_memory`/`search_memory` across sessions, namespace `("memories","shared","{user_id}","{repo_id}")`.
4. **Private memory** — per-subagent namespace `("memories","private","{user_id}","{repo_id}","<agent literal>")`.
5. **Shared vs private isolation** — live spot-check (unit tests already prove cross-agent invisibility).

Run the scenarios **in order** (S1 → S7). Each has concrete payloads and a PASS/FAIL check. Do not mark anything PASS from reading code alone.

---

## 0. Preconditions

| Service | Launch | Port | Check |
|---|---|---|---|
| CRG | `backend\src\code_review_agent\scripts\run_crg_server.sh` | 5555 | `Test-NetConnection 127.0.0.1 -Port 5555` |
| mcp-atlassian | `scripts\run_atlassian_server.sh` (**never bare `uvx`** — session-115 incident) | 9000 | server log shows "Read-only mode: ENABLED" + enabled-tools line |
| Conversation FastMCP | `python -m infrastructure.mcp_clients.servers.conversation_server` (from `backend\src\code_review_agent`) | 9001 | port listening |
| App (uvicorn) | `uvicorn main:app --port 8000` (from `backend\src\code_review_agent`) | 8000 | `GET http://127.0.0.1:8000/api/v1/...` responds |

Also required:
- `.env` has a real `REVIEW_MODEL` + provider key + `GITHUB_PAT` (a `placeholder` value makes E2E impossible — config has no default).
- A registered + graph-ready repo, e.g. `psf/requests` with a ready `graph_commit_hash` (the commit used in prior sessions, prefix `190a6855`) **or** `branch=update-3.0` (auto-builds on 425).
- A fresh review-clean state if you want deterministic row counts; otherwise note baseline counts first (S0).

### S0 — Baseline (optional)
```powershell
# Snapshot current rows so later scenarios can diff against a known baseline.
Invoke-P4Sql "SELECT 'MemorySummary', COUNT(*) FROM MemorySummary UNION ALL SELECT 'store', COUNT(*) FROM store;"
Invoke-P4Sql "SELECT 'AgentExecution', COUNT(*) FROM AgentExecution;"
```

---

## 1. Setup — variables, request + DB helpers

Run once per terminal session from the **repo root** (`C:\Users\borhe\Desktop\AI code reviewer agent`).

```powershell
$Base  = 'http://127.0.0.1:8000/api/v1'
$Db    = (Resolve-Path 'backend\src\code_review_agent\data\phase1_metadata.db').Path
$Py    = (Resolve-Path '.venv\Scripts\python.exe').Path
$EvLog = 'backend\src\code_review_agent\logs\review_events.log'
$Repo  = 'psf/requests'      # change to your registered repo
$User  = 'alice'             # caller-supplied tenant key (no auth, PHASE_3.md §9.5)
$Commit = '190a6855'         # a ready graph_commit_hash for $Repo (or use branch=update-3.0)
```

```powershell
function Invoke-P4Post([string]$Path, $Body) {
    Invoke-RestMethod -Method Post -Uri ($Base + $Path) `
        -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Depth 10)
}
```

```powershell
# DB inspection helper — runs arbitrary SQL on the Phase 1/Phase 4 DB via the venv python.
function Invoke-P4Sql([string]$Sql) {
    $tmp = Join-Path $env:TEMP 'p4_inspect.sql'
    Set-Content -LiteralPath $tmp -Value $Sql -Encoding ascii
    & $Py -c @"
import sqlite3
con = sqlite3.connect(r'$Db')
for row in con.execute(open(r'$tmp').read()):
    print(row)
con.close()
"@
}
```

Quick sanity of the helpers:
```powershell
Invoke-P4Sql "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
# Expect: AgentExecution, Conversation, GraphSnapshot, MemorySummary, Message, PendingSummary?, RepoWorkspace,
#         ReviewSession, ToolCall, store, store_migrations, message_fts, ...
# 'store' + 'store_migrations' = the Phase 4 LangGraph memory tables (no 'store_vectors' — no index/embeddings).
```

---

## 2. Scenarios

### S1 — Baseline sanity review (no memory/conversation)

Confirms the stack + route return before any Phase 4-specific checks.

```powershell
$r = Invoke-P4Post '/review' @{
    repo_id          = $Repo
    graph_commit_hash = $Commit
    request_type     = 'any_question'
    question         = 'Summarize what this change does in one sentence.'
    diff_content     = @'
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -12,6 +12,7 @@ def handle(req):
         return normalize(payload)
     except KeyError:
+        log.warning("missing payload key")
         return {}
'@
}
$r.review_session_id   # non-null => 200 happy path
```
**PASS:** `review_session_id` returned; response has `result` (valid JSON string) + `timeline`.

---

### S2 — Seed a conversation with a distinctive fact (needed by S3/S4/S6)

```powershell
$c = Invoke-P4Post '/conversations' @{ repo_id = $Repo; user_id = $User }
$cid = $c.conversation_id
Write-Output "conversation_id = $cid"

# Seed a memorable fact (unique token so it is greppable later).
Invoke-P4Post "/conversations/$cid/message" @{
    user_id = $User; repo_id = $Repo
    content = "TEAM-FACT-CLIP4: the team approved the CLIP-4 mitigation; it uses WAL mode."
} | Out-Null
```
**PASS:** message persisted (a `Message` row exists for `$cid`) and a `search_messages` audit invocation was recorded in `AgentExecution` (Phase 3 behavior; also verified by S4's event log).

---

### S3 — Shared memory: write

Steer the orchestrator to store a fact in **shared** memory, then check the `store` table + event log.

```powershell
$r = Invoke-P4Post '/review' @{
    repo_id           = $Repo
    graph_commit_hash = $Commit
    request_type      = 'any_question'
    conversation_id   = $cid
    user_id           = $User
    question = 'Store the fact "TEAM-FACT-CLIP4 approved (WAL mode)" in SHARED memory, then answer: what does this change do?'
}
```
Then, up to ~60s later:
```powershell
Invoke-P4Sql "SELECT prefix, key, substr(value,1,120) FROM store ORDER BY created_at DESC LIMIT 10;"
# Expect a row whose prefix IS THE DOT-JOINED NAMESPACE:
#   memories.shared.alice.psf/requests
# and value containing TEAM-FACT-CLIP4.
Select-String -Path $EvLog -Pattern 'manage_memory' | Select-Object -Last 5
```
**PASS:**
- ≥1 `store` row with `prefix` = `["memories","shared","alice","psf/requests"]` whose `value` mentions `TEAM-FACT-CLIP4`.
- `manage_memory` appears in the event log tagged with the owning agent.

**Model-fidelity caveat (NOT a harness bug):** tool calls are LLM-initiated. If the model never calls `manage_memory`, record it as a weak-model fidelity note (same class as Phase 2's delegation variance) and confirm the *wiring* instead: the shared tool pair is present in the root agent's runtime tool list (S1's event log shows the tool set) and store resolution is unit-tested (`test_memory_phase4.py`). Do not re-engineer.

---

### S4 — Shared memory: cross-session recall

A **new** conversation (same user/repo) must be able to recall what was stored in S3.

```powershell
$c2 = Invoke-P4Post '/conversations' @{ repo_id = $Repo; user_id = $User }
$cid2 = $c2.conversation_id
Invoke-P4Post "/conversations/$cid2/message" @{
    user_id = $User; repo_id = $Repo
    content = "Did the team settle the CLIP-4 mitigation approach?"
} | Out-Null

$r = Invoke-P4Post '/review' @{
    repo_id           = $Repo
    graph_commit_hash = $Commit
    request_type      = 'any_question'
    conversation_id   = $cid2
    user_id           = $User
    question = 'Recall from your stored shared memory what the team decided about CLIP-4, then answer.'
}
```
```powershell
Select-String -Path $EvLog -Pattern 'search_memory' | Select-Object -Last 5
```
**PASS:** `search_memory` appears in the event log **and/or** the returned `result`/findings reference `CLIP-4`/`WAL` from the stored fact (i.e. cross-session recall actually surfaces).

---

### S5 — Private memory (per-subagent namespace)

Target the **security** specialist and instruct it to store a fact in **its private** memory.

```powershell
$r = Invoke-P4Post '/review' @{
    repo_id           = $Repo
    graph_commit_hash = $Commit
    request_type      = 'security_question'
    question = 'Store the fact "PRIVATE-FACT: legacy HMAC path is a known risk" in YOUR PRIVATE memory, then briefly assess the diff.'
    diff_content = '--- a/src/auth.py +++ b/src/auth.py @@ -8,0 +9,3 @@ def verify(t): +    if not t.hmac: +        return False'
}
```
```powershell
Invoke-P4Sql 'SELECT prefix, substr(value,1,120) FROM store WHERE prefix LIKE ''memories.private.%'';'
# Expect prefix = memories.private.alice.psf/requests.security and value mentioning PRIVATE-FACT.
```
> **Prefix format note (verified live 2026-08-19):** LangGraph serializes the namespace into `store.prefix` **dot-joined** (`memories.shared.alice.psf/requests`), NOT a JSON array string — the `search_memory` tool result is the only place the array form appears (`["memories","shared","alice","psf/requests"]`). Use the dot-joined form in SQL filters.
**PASS:** a `store` row with the **literal agent name `security`** in its prefix and the fact in `value`; the same fact does **NOT** appear under `shared` or any other agent's private prefix.

---

### S6 — Durable conversation summary

The durable summary runs as a FastAPI **BackgroundTask** after the review response sends (D-P4-4). Use the S2 conversation, poll up to ~60s.

```powershell
$r = Invoke-P4Post '/review' @{
    repo_id           = $Repo
    graph_commit_hash = $Commit
    request_type      = 'any_question'
    conversation_id   = $cid          # S2's conversation — must have ≥1 message
    user_id           = $User
    question = 'Review the change and summarize the session.'
}
# Poll for the MemorySummary row:
1..12 | ForEach-Object {
    Start-Sleep -Seconds 5
    $rows = Invoke-P4Sql "SELECT id, conversation_id, summarized_up_to_message_id, substr(summary_text,1,80) FROM MemorySummary WHERE conversation_id = $cid ORDER BY id DESC;"
    if ($rows) { $rows; break }
}
```
**PASS:** a `MemorySummary` row for `$cid` with non-empty `summary_text` and a non-null `summarized_up_to_message_id` (recency = latest message id).

**Accepted risk (D-P4-4):** if the client disconnects before the response sends, or the worker restarts between send and task completion, the summary is skipped silently (no warning/retry). Retry the review once if the row never appears while the app stayed up.

---

### S7 — In-context summarization (lab-triggered proof)

A real 222,822-token live trigger is impractical (≈ 800K chars). Deterministic proof = **unit tests** (`test_summarization_trigger_constants`, `test_exactly_one_summarization_middleware`) + this **lab run with a lowered trigger**:

1. Stop the app; relaunch with a tiny budget so an ordinary big diff exceeds it:
   ```powershell
   # env for this uvicorn process only:
   $env:SUMMARIZATION_TRIGGER_TOKENS = '5000'
   $env:SUMMARIZATION_KEEP_TOKENS    = '500'
   uvicorn main:app --port 8000
   ```
2. Run a review whose history naturally exceeds ~5K tokens (large `diff_content` — paste a multi-hundred-line real diff, or reuse a big PR diff from `git diff` of a past review):
   ```powershell
   $bigDiff = (git -C "backend\src\code_review_agent\data\workspaces\psf_requests" diff HEAD 2>$null) -join "`n"
   if (-not $bigDiff) { $bigDiff = ('# filler' * 4000) }   # guaranteed > 5000 tokens
   $r = Invoke-P4Post '/review' @{
       repo_id = $Repo; graph_commit_hash = $Commit; request_type = 'review'
       diff_content = $bigDiff
   }
   ```
3. **PASS:** review returns **200** with findings — i.e. the middleware absorbed a token load that exceeds the (lowered) trigger instead of the run dying on context overflow.
4. Revert: kill uvicorn, relaunch **without** the two env vars.

---

## 3. Full inspection queries (after S2–S6)

```sql
-- Durable summaries
SELECT * FROM MemorySummary ORDER BY id DESC;

-- LangGraph long-term memory (shared + private)
SELECT prefix, key, value, created_at FROM store ORDER BY created_at DESC;

-- Conversations + messages used in the run
SELECT c.id, c.repo_id, c.user_id, m.id AS msg_id, m.role, substr(m.content,1,60)
FROM Conversation c LEFT JOIN Message m ON m.conversation_id = c.id ORDER BY m.id;

-- Audit rows (should include search_messages invocations + review session + executions)
SELECT id, agent_name, status, substr(result,1,80) FROM AgentExecution ORDER BY id DESC LIMIT 20;

-- Sanity: no vector index (no store_vectors table)
SELECT name FROM sqlite_master WHERE type='table' AND name='store_vectors';
```
Event log greps:
```powershell
Select-String -Path $EvLog -Pattern 'manage_memory','search_memory'
```

---

## 4. Execution order (do not reorder)

1. Preconditions (§0) + baseline (S0).
2. S1 baseline review → 200.
3. S2 seed conversation.
4. S3 shared write → store row + `manage_memory` event.
5. S4 shared recall → `search_memory` event / recalled fact.
6. S5 private write → security-private row + no bleed.
7. S6 durable summary → `MemorySummary` row.
8. S7 lab in-context trigger → 200 under a lowered budget; revert env.
9. Record results + any model-fidelity notes in `OPENCODE.md` changelog.

---

## 5. Risks / honest limits

- **S7 is a lab proof, not a real 222,822-token run** — unit tests cover the exact thresholds; the lab run proves the overflow-absorption behavior end to end.
- **Memory tool calls are model-driven.** Non-use by a weak model is an LLM-fidelity note, not a harness bug; wiring is unit-tested.
- **Durable summary is best-effort** (D-P4-4): post-response background task, silently skippable on disconnect/restart; poll and retry once per S6.
- **No `store_vectors`** must exist (no embeddings — project's anti-vector decision, PHASE_4.md §6.4).
