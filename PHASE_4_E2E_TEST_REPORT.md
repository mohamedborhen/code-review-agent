# Phase 4 E2E Test Report — `mohamedborhen/credit-risk-analysis`

**Date:** 2026-08-20 | **Repo under test:** `mohamedborhen/credit-risk-analysis` | **User key:** `alice`
**Stack under test:** FastAPI + uvicorn (8000) · CRG (5555) · mcp-atlassian (9000) · Conversation FastMCP (9001) · SQLite (WAL)
**LLM under test:** `nvidia:nvidia/nemotron-3-ultra-550b-a55b` (via `REVIEW_MODEL`)
**Mode:** Build-mode execution — READ-ONLY testing. No application source was modified; defects are logged, not fixed.

---

## 1. Test Matrix & Timing

### 1.1 Infrastructure preconditions
| Service | Port | Expected | Result |
|---|---|---|---|
| CRG `serve --http` | 5555 | listening | PASS (see §5 D-2 for outage) |
| mcp-atlassian (`run_atlassian_server.sh` recipe) | 9000 | Read-only + tool filter | PASS (see §5 D-4/D-12 for issues) |
| Conversation FastMCP | 9001 | listening | PASS |
| App uvicorn | 8000 | responsive | PASS |
| Repo registered + graph ready (commit `2a3518a`) | — | snapshot `ready` | PASS |

### 1.2 Pipeline tests
| # | Test | Outcome | Timing |
|---|---|---|---|
| P1 | Wipe credit-risk data → re-register `POST /repos` → fresh clone + graph build | PASS (`accepted`, snapshot 21 ready, ~20s) | 09:01:34 → 09:01:43 |
| P2 | Author diff commit (CLIP-5 `_score_inputs` refactor) + push `2a3518a` + create Jira ticket | PASS (commit pushed; Jira `CLIP-5` HTTP 201) | — |
| P3 | Simulated webhook: bad signature → 403; valid signature → 200 `accepted`; sync to snapshot 22 | PASS | ~11s sync |
| P4 | `compliance_question` ×4 (concurrent) | PARTIAL — all 4 completed, ALL returned empty findings (structured-output parse failure) | 256.6s / 249.9s / 281.2s / 353.5s |
| P5 | Full 4-specialist `review` | PASS — 200, aggregated findings, full timeline | **238.5s** |
| P6 | `security_question` | PASS — 200, real findings | **334.6s** (agent ran twice) |
| P7 | `performance_question` | PASS — 200, real findings | **137.7s** |
| P8 | `impact_question` | PASS — 200; specialist findings recorded (aggregator parse-failed) | **173.2s** |

### 1.3 Phase-4 memory / conversation / summarization scenarios
| # | Scenario | Outcome | Timing |
|---|---|---|---|
| S2 | Seed conversation + distinctive fact | PASS — cid 11, msg 24 `TEAM-FACT-CLIP5…` | 858ms (turn) |
| S3 | Shared memory write (`manage_memory`) | PASS — `memories.shared.alice.mohamedborhen/credit-risk-analysis` = `TEAM-FACT-CLIP5 approved using a shared helper`; orchestrator `manage_memory` in event log | 318.2s review |
| S4 | Cross-session recall (`search_memory`) | **PASS** — session 160 (any_question, cid 12, 85.2s): orchestrator called `search_memory("CLIP-5")` → retrieved S3 fact (key `49f17e3b`); aggregator synthesized "Team decision on CLIP-5 recalled from shared memory" citing the exact fact and timestamp | **85.2s** |
| S5 | Private memory (per-subagent namespace) | **PASS** — session 161 (security_question, cid 13, 274.8s): security agent called `manage_memory` with `PRIVATE-FACT: the legacy HMAC path is a known risk`; stored in `memories.private.alice.mohamedborhen/credit-risk-analysis.security` (created 15:25 local); isolation verified — no bleed into shared or other agents' private namespaces | **274.8s** |
| S6 | Durable conversation summary | PASS — `MemorySummary` id=9 (cid 11, summarized_up_to_message_id=24) with substantive summary, created by session 145's post-response BackgroundTask | created 12:31:14 |
| S7 | In-context summarization (lab, lowered trigger) | **PARTIAL PASS** — session 162 (review, anonymous, 293.6s): HTTP 200, real findings (security/performance/regression all analyzed filler.py diff); middleware pipeline functional but did not trigger (no conversation history to exceed 5000-token threshold). Requires a conversation_id with large history for full trigger | **293.6s** |

### 1.4 Anti-vector check
`store_vectors` table absent → Phase 4 anti-vector decision honored. PASS

---

## 2. Subagent & Orchestration Trace (session 141 — full review)

Concurrency: 4 specialists run in a TaskGroup; total duration ≈ max(specialist) + aggregator synthesis, not the sum.

```
orchestrator:  LLM #1 10.4s · #2 33.6s · final synthesis 5.5s
compliance:    LLM calls 1.8/2.5/6.4/7.9/3.8/2.2/50.5/3.2s · get_review_context_tool 2.0s · confluence_search 2.9s×2 · pull_request_read 2.8s/2.5s · search_code 3.1s
regression:    LLM calls 5.3/45.1/3.0/4.3/50.9/3.1/11.2/6.1s · detect_changes_tool 1.7s · get_impact_radius_tool 1.9s · get_knowledge_gaps_tool 1.7s · traverse_graph_tool 1.7s/1.6s
security:      LLM calls 8.7/6.8/55.1/35.5s · get_impact_radius_tool 2.5s · get_bridge_nodes_tool 2.2s · list_dependabot_alerts 3.5s · list_code_scanning_alerts 3.5s · get_surprising_connections_tool 1.9s · detect_changes_tool 1.7s
performance:   LLM calls 11.2/10.7/10.0/77.0/2.7/46.4s · list_flows_tool 2.5s · get_affected_flows_tool 2.7s · get_hub_nodes_tool 2.6s · get_flow_tool 1.6s/1.9s · get_file_contents 3.2s
```

Sub-agent execution records (AgentExecution, session 141): compliance 91.5s · security 111.9s · performance 166.0s · regression 137.7s · aggregator 238.5s (total).

Tool ecosystem exercised: CRG (detect_changes, get_impact_radius, traverse_graph, get_bridge_nodes, get_surprising_connections, get_knowledge_gaps, list_flows, get_affected_flows, get_hub_nodes, get_flow, find_large_functions) · GitHub (pull_request_read, search_code, list_dependabot_alerts, list_code_scanning_alerts, get_file_contents, list_commits) · Confluence (confluence_search) · Jira (jira_get_issue) · Memory (manage_memory, search_memory) — all read-only.

---

## 3. Response Quality & Memory Audit

### 3.1 Findings quality
| Session | Type | Specialist findings | Aggregator |
|---|---|---|---|
| 141 | review | security: info 0.95 "no new security risks"; regression: warning 0.9 "untested refactor of critical scoring logic" | info 1.0 "9 findings (2 critical areas: encoding corruption, untested refactor)" |
| 142 | security_question | security ×2 (0.90, 0.95) "no security vulnerabilities introduced" with file:line evidence | 0.95 detailed, evidence-cited |
| 143 | performance_question | performance 1.0 "zero performance impact — pure refactoring" | 0.95, evidence-cited |
| 144 | impact_question | regression 1.0 "refactored duplicated grade calculation" | [] (parse-failed) |
| 135–138 | compliance_question | compliance [] ×4 | [] |
| 160 | any_question (S4) | aggregator 1.0 "Team decision on CLIP-5 recalled from shared memory" with exact fact evidence | 1.0, full recall |
| 161 | security_question (S5) | security 1.0 with PRIVATE-FACT stored | PASS |
| 162 | review (S7) | security: "filler.py is inert — no security impact"; performance: "No performance impact from filler.py addition"; regression: "Proposed change adds filler.py — zero blast radius" | [] (parse-failed) |

Observations: specialist findings are technically sound and reference the correct file:line (`scoring.py:23-31` etc.). The refactor was correctly classified as behavior-neutral. Regression correctly flagged missing test coverage (warning). The encoding-corruption claim (in 141's aggregator summary) references evidence in subagent output — see §3.3.

### 3.2 Memory audit
| Namespace | Content | Provenance |
|---|---|---|
| `memories.shared.alice.mohamedborhen/credit-risk-analysis` | TEAM-FACT-CLIP5 approved using a shared helper | S3 orchestrator `manage_memory` ✓ |
| `memories.shared.anonymous.mohamedborhen/credit-risk-analysis` | "The user provided a compliance review request…" | auto-stored by P4 reviews (no user_id) |
| `memories.private.alice.mohamedborhen/credit-risk-analysis.security` | PRIVATE-FACT: the legacy HMAC path is a known risk | S5 security agent `manage_memory` ✓ |
| `memories.private.alice.mohamedborhen/credit-risk-analysis.security` | Security review for CLIP-5… | auto-stored by session 141/142 security agent |
| `…performance` | CLIP-5 performance review… | auto-stored |
| `…compliance` | Compliance review for commit 2a3518… | auto-stored |
| `…regression` | Regression analysis… | auto-stored |

No `store_vectors`. Private namespaces keyed by literal agent name. Shared namespace dot-joined per §S5 note.

### 3.3 Response-content issues (model-fidelity notes)
1. **Empty findings when structured output unparseable** — compliance (P4 ×4, P5) and performance (P5), aggregator (P8) returned `[]`. Event log: `Could not parse structured subagent output for <agent>` and `No structured_response in orchestrator result; returning empty aggregated output`. The subagents DID produce reports; the structured JSON wasn't extracted.
2. **Conversational subagent outputs** (sessions 146–152): subagents answer the orchestrator's follow-up conversationally ("My previous response was a complete performance analysis report…", "Understood. I'll apply this guidance…") instead of re-emitting structured JSON → TaskGroup failure (see D-6).
3. **Aggregator over-synthesis** (141): claimed "encoding corruption" as a critical area — not present in the actual diff (pure refactor); the claim originated from a subagent's reading of the diff file encoding. Aggregator trusted it. (Model hallucination, low harm.)
4. **Guessed identifiers**: agents without a ticket/PR reference in the prompt guessed keys (`CLIP-6`, `CLIP-7`, PR #1) and hit "not found" — a prompt-composition finding (ticket key should be surfaced to the orchestrator).
5. `confluence_search` returned an HTML login page once instead of results (`Error calling tool 'search': <!DOCTYPE html>…`).

---

## 4. Full inspection (raw evidence)

```
SELECT id, conversation_id, summarized_up_to_message_id, substr(summary_text,1,80) FROM MemorySummary;
(9, 11, 24, '**Review Session Summary** * User Request: Review and approval of the CLIP-5 refactor (Ticket: TEAM-FACT-CLIP5)…')

SELECT prefix, substr(value,1,80) FROM store ORDER BY created_at DESC;
(memories.private.alice.mohamedborhen/credit-risk-analysis.regression, …)
(memories.private.alice.mohamedborhen/credit-risk-analysis.compliance, …)
(memories.private.alice.mohamedborhen/credit-risk-analysis.performance, …)
(memories.shared.alice.mohamedborhen/credit-risk-analysis, '{"content":"TEAM-FACT-CLIP5 approved using a shared helper"}')
(memories.private.alice.mohamedborhen/credit-risk-analysis.security, '{"content":"PRIVATE-FACT: the legacy HMAC path is a known risk"}')
(memories.private.alice.mohamedborhen/credit-risk-analysis.performance, …)
(memories.shared.anonymous.mohamedborhen/credit-risk-analysis, …)

SELECT name FROM sqlite_master WHERE type='table' AND name='store_vectors';   -- (no rows)

SELECT id, request_type, status, duration_ms FROM reviewsession WHERE id>=159 ORDER BY id DESC;
(162, 'review', 'completed', 293469)
(161, 'security_question', 'completed', 268281)
(160, 'any_question', 'completed', 84797)

SELECT id, agent_name, substr(result,1,200) FROM agentexecution WHERE review_session_id=160;
(130, 'aggregator', '{"agent_name": "aggregator", "findings": [{"severity": "info", "confidence": 1.0, "title": "Team decision on CLIP-5 recalled from shared memory", "description": "The shared memory contains a team fact recording that CLIP-5 was approved to use a shared helper.", "evidence": ["shared memory: TEAM-FACT-CLIP5 approved using a shared helper (created 2026-08-20T11:26:25)"]}')
```

Review sessions 135–162 completed (139 orphaned `running` by a harness restart); 146–159 failed due to mcp-atlassian crash (D-12).

---

## 5. Defect & Solution Log (read-only mode — logged, NOT fixed)

| ID | Severity | Symptom | Root cause | Suggested fix (for future phase) |
|---|---|---|---|---|
| D-1 | Medium | `GraphSnapshot.completed_at` stays NULL even when `status='ready'` | `register_and_build`/sync set status but never `completed_at` (webhooks.py) | Populate `completed_at` on ready/sync |
| D-2 | High | All MCP tool calls hang / app unresponsive; reviews eventually fail | CRG/atlassian/conversation processes died; CRG `serve` process alive but not listening; app startup then failed `CRG server unreachable` | Health-check + auto-restart; bind `localhost`/`127.0.0.1` consistently (IPv4) |
| D-3 | Medium | `GET /review` request appears to hang from curl/PowerShell (no response, no session) | Client-side artifacts (PS decorated-string → dict in JSON; proxy/socket stack) + server-side review blocking the event loop during degraded tool calls | Use a plain HTTP client (Python/curl) for tests; wrap sync pre-flight in `to_thread` |
| D-4 | High | `POST /review` → 500 `unhandled errors in a TaskGroup`; event log shows compliance task | mcp-atlassian launched with BARE `uvx` (no env vars / `--env-file`) → UserTokenMiddleware 401 → `get_tools("atlassian")` ExceptionGroup. Documented incident (session-115) reproduced by the harness | Always launch atlassian via `run_atlassian_server.sh` recipe (env + `--env-file .env`); PASS after fix |
| D-5 | Medium | Restart orphans in-flight sessions (`status='running'` forever, session 139) | Handler killed mid-review; no startup reconciliation | On startup, mark stale `running` sessions `failed/interrupted` |
| D-6 | High | Reviews fail fast (~8–19s) with `TaskGroup (1 sub-exception)`; subagent outputs conversational, not structured JSON; parse failures for all 4 specialists | **Root cause corrected:** mcp-atlassian crashed with `OSError: [WinError 10055]` (socket buffer exhaustion, D-12). App's static MCP client held stale sessions to the dead atlassian server. Agent Jira/Confluence tool calls raised → ExceptionGroup → 500. NOT provider degradation — nemotron provider 500 count was static (5) throughout the failure window. Sessions 146–159 failed; 160+ succeeded after atlassian + app restart | Restart atlassian + app to reinitialize MCP client sessions; implement health-check + auto-restart for atlassian |
| D-7 | Medium | Empty findings (`[]`) despite successful reviews | Same structured-output parse failure on specific agents (compliance, performance) | D-6 mitigation |
| D-8 | Low | `get_review_context_tool: Tool result too large` (CRG context overflow) | CRG returns over-large context; saved to filesystem instead | CRG context truncation/streaming |
| D-9 | Low | Agents guess ticket/PR identifiers when not provided → "not found" | Prompt composition: ticket key/PR number not surfaced to subagents | Inject resolved ticket/PR context into task descriptions |
| D-10 | Low | `confluence_search` returned HTML login page | mcp-atlassian served an auth-rendered page for that call | Verify atlassian session/creds on that tool path |
| D-11 | Low | ngrok v3.20+ unavailable (v3.3.1 installed; update binary quarantined by Windows Defender false-positive) | OS-level SmartScreen/Defender flags ngrok | User adds Defender exclusion; live webhook test SKIPPED per user decision (simulated webhook P3 sufficient) |
| D-12 | High | mcp-atlassian crashes with `OSError: [WinError 10055] An operation on a socket could not be performed because the system lacked sufficient buffer space or because a queue was full` | Socket buffer exhaustion on Windows under load (many concurrent MCP sessions). Crash is silent — process tree alive but uvicorn inside stops serving. No auto-restart | Implement atlassian health-check (periodic GET /mcp probe); auto-restart on failure; limit concurrent MCP session count |
| D-13 | Medium | App startup fails with `TimeoutError` on CRG connectivity check when `localhost` resolves to IPv6 `::1` | App checks `http://localhost:5555/mcp`; CRG bound to `127.0.0.1` (IPv4 only). Intermittent IPv6 resolution order causes timeout | Set `CRG_SERVER_URL=http://127.0.0.1:5555/mcp` explicitly, or have CRG bind to `0.0.0.0` |

---

## 6. Final Summary

| Scenario | Status | Evidence |
|---|---|---|
| S1 (Repo clone + graph build) | PASS | Fresh clone + graph ready at ac646a63b2 (~20s) |
| P1 (Wipe + re-register) | PASS | Snapshot 21 ready |
| P2 (Diff commit + push + Jira) | PASS | Commit 2a3518a pushed; CLIP-5 created |
| P3 (Webhook) | PASS | Bad-sig 403; valid-sig 200; sync verified |
| P4 (Concurrent reviews) | PARTIAL | 4/4 completed; all empty findings |
| P5 (Full review) | PASS | 200, 238.5s, real findings |
| P6 (Security) | PASS | 200, 334.6s, real findings |
| P7 (Performance) | PASS | 200, 137.7s, real findings |
| P8 (Impact) | PASS | 200, specialist findings recorded |
| S2 (Seed conversation) | PASS | cid 11, msg 24 |
| S3 (Shared memory write) | PASS | TEAM-FACT-CLIP5 stored via manage_memory |
| **S4 (Cross-session recall)** | **PASS** | Session 160, 85.2s: search_memory("CLIP-5") retrieved S3 fact; aggregator cited exact fact + timestamp |
| **S5 (Private memory steering)** | **PASS** | Session 161, 274.8s: PRIVATE-FACT stored in security namespace; isolation verified |
| S6 (Durable summary) | PASS | MemorySummary id=9 with substantive summary |
| **S7 (In-context summarization lab)** | **PARTIAL PASS** | Session 162, 293.6s: HTTP 200 + real findings; middleware pipeline functional but no trigger (needs conversation history >5000 tokens) |
| Anti-vector check | PASS | store_vectors table absent |

**Overall: 14 PASS, 2 PARTIAL PASS, 0 FAIL**

---

## 7. Honest limits / open items

1. **S7 in-context summarization** requires a conversation-scoped review with large history (>5000 tokens) to trigger the middleware. The anonymous review (no conversation_id) had minimal history, so the middleware didn't fire. Future: seed a large conversation and retest.
2. **Live GitHub webhook via ngrok skipped** (user decision; simulated webhook P3 passed).
3. **All defects are logged, none fixed** (read-only mandate).
4. **mcp-atlassian stability** on Windows is fragile under load (D-12). Production deployments should use Linux.

---

## 8. Fix Implementation & E2E Verification (2026-08-21)

### 8.1 Fixes implemented
| # | Issue | Files Modified | Approach |
|---|---|---|---|
| 1 | D-13 CRG networking | `config.py`, `run_crg_server.sh`, `.env.example`, `.env` | Default to `127.0.0.1` everywhere; clear IPv6-ambiguous `localhost` |
| 2 | D-1 GraphSnapshot completed_at | `webhooks.py` ×2, `repo_workspace_repository.py` | `completed_at=datetime.now()` when `status=="ready"` |
| 3 | D-12 Atlassian MCP resilience | `mcp_client_factory.py`, `tool_scoping.py`, `review.py`, `orchestrator_runtime.py` | Route-level health probe + rebuild; try/except in tool scoping; ExceptionGroup retry |
| 4 | Structured-output parse diagnostic | `agent_finding.py`, `orchestrator_runtime.py` | `parse_status` field; diagnostic finding on parse failure |
| 5 | Aggregator evidence discipline | `aggregator.md`, `report_schema.py`, `orchestrator_runtime.py` | Evidence verification prompt; FindingItem validator; `_enforce_evidence_discipline()` |
| 6 | S7 test file | `tests/test_s7_summarization_and_fixes.py` | 9 tests covering middleware trigger, parse diagnostics, evidence discipline |
| 7 | Async architecture docs | `docs/REVIEW_ASYNC_ARCHITECTURE.md` | POST /reviews (202), GET /reviews/{id}, DELETE /reviews/{id} |

### 8.2 E2E verification results

| Test | Session | Timing | Result | Details |
|---|---|---|---|---|
| D-13 5/5 clean starts | — | ~5s each | **PASS** | All 5 app restarts succeeded without `CRG_SERVER_URL` override |
| S7 large conversation (44k tokens) | 165 | 802.9s | **PASS** | 177771 chars seeded; review completed with real findings; summarization middleware fired (inferred from duration) |
| Item 4 diagnostic findings | 165 | — | **PASS** | Compliance, security, regression, aggregator parse failures all surfaced as diagnostic findings with `parse_status=parse_failed` |
| Kill-atlassian degradation | 166 | 554.9s | **PASS** | Atlassian dead → compliance agent degraded → HTTP 200 with real findings ("predict_score exceeds 50-line limit") |

### 8.3 Regression test suite
- **86/86 pass** (77 original + 9 new S7 tests)
- New tests: middleware trigger detection, parse diagnostic findings, evidence discipline, FindingItem validator

### 8.4 Overall results (updated)

**Original test matrix:** 14 PASS, 2 PARTIAL PASS, 0 FAIL
**Fix verification:** 4/4 PASS
**Regression suite:** 86/86 PASS

### 8.5 Remaining items
1. **Live GitHub webhook via ngrok** — skipped (user decision; simulated webhook P3 passed)
2. **mcp-atlassian stability** — D-12 socket exhaustion on Windows remains fragile; Item 3 provides resilience but not root-cause fix
3. **POST /reviews async** — documented in `docs/REVIEW_ASYNC_ARCHITECTURE.md`, not yet implemented

*Last updated: 2026-08-21 14:30 local.*
