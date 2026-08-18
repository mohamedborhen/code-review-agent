# Phase 3 — Stateful Conversation Persistence, Conversation FastMCP, and Context Retrieval

**Status:** Implemented & verified — post-implementation architecture and operational specification.
**Phase:** 3
**Predecessors:** Phase 1 — Ingestion & Knowledge Graph Pipeline; Phase 2 — Stateless Multi-Agent Review Core.
**Primary goal:** Persist conversation history and make that history safely retrievable by the Phase 2 Review Orchestrator when the orchestrator determines that historical context is useful.
**Implementation note:** This document describes the final Phase 3 architecture as built. Test execution status must be taken from the project test/E2E reports; this document does not claim that tests passed unless recorded there.

> **Important:** Phase 3 adds a conversation-history substrate and a retrieval boundary. It does **not** implement the complete memory architecture. Shared Memory, Private Memory, and LangMem-based summarization are intentionally deferred to Phase 4. This document's final section (§20) is the explicit handoff contract for the Phase 4 architect.

---

## 0. How to use this document

This is the authoritative reference for Phase 3. Anyone who has never seen this phase should be able to reconstruct its architecture, security model, data flows, and runtime wiring from this file alone.

Section 1 lists the non-negotiable compliance constraints. Section 2 is the compliance matrix mapping each requirement to its implementation. Sections 3–19 document the architecture, schema, contracts, security, runtime, and tests. Section 20 is the Phase 3→4 handoff.

---

## 1. Non-negotiable compliance constraints

These come directly from the existing Phase 1/2 architecture and the Phase 3 pre-flight audit resolutions. They remain in force as built:

- **5-layer clean architecture is mandatory.** Domain layer (Layer 4) code (`domain/entities/conversation_entity.py`) contains zero imports of `fastapi`, `deepagents`, `langchain_mcp_adapters`, `pydantic`, `git`/`subprocess`, `mcp`, or `sqlmodel` — same rule already enforced on `AgentFinding`/`AgentOutput`.
- **File Placement Discipline.** All ORM models are appended to `infrastructure/db/models.py` (never a `models/` directory, which collides with the module import). Application services live under `application/conversation_service/`.
- **Sync/Async execution boundaries.** FastMCP tool invocations and synchronous SQLite transactions must never block the FastAPI event loop. SQLite persistence calls are wrapped in `asyncio.to_thread`; the FastMCP server's synchronous search core runs via `fastapi.concurrency.run_in_threadpool`.
- **SQLite concurrency settings match Phase 1**: `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` on every connection that touches the new tables. Phase 3 additionally enables `PRAGMA foreign_keys=ON` on every connection (required for `ON DELETE CASCADE` to fire).
- **MCP registration follows the existing `MultiServerMCPClient` lifespan pattern.** The Conversation FastMCP server is the 5th streamable-HTTP server in the static client constructed once at FastAPI startup (`app.state.mcp_client`). No second or per-request MCP client is ever created.
- **Static Client Identity Transport.** Because `MultiServerMCPClient` headers are static per-server configs set once at startup, dynamic identity attributes (`user_id`, `repo_id`, `conversation_id`) are passed as explicit typed arguments to `search_messages`, populated by Layer 3 Application orchestration from the API request body. There is no auth middleware in the codebase — `POST /conversations` and `POST /conversations/{id}/message` accept `user_id` and `repo_id` in the request body, and the Layer 3 orchestrator forwards them verbatim into `search_messages`, where the §8.2 authorization check runs server-side.
- **Identity is closure-bound for the LLM, never LLM-supplied.** The audited context tool granted to the orchestrator root agent binds `conversation_id`/`user_id`/`repo_id` at construction time (server-side, before the LLM ever sees the tool). Its LLM-visible `args_schema` exposes ONLY `query`/`limit`/`exclude_message_id` with `extra="forbid"`, so a hostile/injected call that tries to smuggle identity keys is REJECTED at schema validation (pydantic `ValidationError`) — never silently overridden downstream. The underlying `search_messages` tool still takes identity as explicit typed args (the turn-flow path is unaffected).
- **Explicit tool lists only.** The Conversation MCP registers a named, minimal tool list (`["search_messages"]`) — never a wildcard.
- **The Context Agent is read-only, full stop.** It is granted ONLY the `search_messages` tool. No tool that can INSERT, UPDATE, or DELETE conversation data is ever exposed to it.
- **No `execute_sql`-style tool, ever.** Every tool this MCP exposes is a rigid, typed Python function. SQL is written and controlled by backend code.
- **Audit discipline matches `ReviewSession`/`AgentExecution`.** Context Agent invocations are logged to `AgentExecution` via `json.dumps(dataclasses.asdict())`, on success AND failure. **Never log message content or snippet text** into audit tables.
- **Startup Wiring Exception.** An explicit, documented exception is granted in `infrastructure/db/engine.py` to execute raw DDL during `init_db()` for the `message_fts` FTS5 virtual table, its 3 sync triggers (`message_ai`, `message_ad`, `message_au`), and the `_rebuild_agentexecution()` 4-step table-rebuild migration.
- **FTS5 Query Protection.** Input queries in `search_messages` MUST be phrase-quoted (`'"' + query.replace('"', '""') + '"'`) before running FTS `MATCH` statements to prevent SQLite `OperationalError` when searching hyphenated terms (e.g. `CLIP-4`).
- **`tool_name_prefix` stays at its default (`False`)** on `MultiServerMCPClient`. No prefix-stripping or fuzzy matching in `scoped()`.
- **`handle_tool_errors` stays at its default (`True`)**: an MCP tool failure returns a `ToolMessage(status="error")` for the agent to handle instead of crashing the review.

---

## 2. Compliance matrix (requirement → implementation)

| Requirement | Where implemented | Status |
|---|---|---|
| 5-layer clean architecture; zero framework imports in domain | `domain/entities/conversation_entity.py` (dataclasses only) | ✅ |
| ORM models appended to `infrastructure/db/models.py` | `Conversation`, `Message`, `ToolCall`, `MemorySummary` (`__tablename__` PascalCase) | ✅ |
| WAL + `busy_timeout=5000` on all DB connections | `engine.py` connect listener; `conversation_server._connect()` | ✅ |
| `PRAGMA foreign_keys=ON` | `engine.py` connect listener; `conversation_server._connect()` | ✅ |
| Conversation FastMCP = 5th server in shared `MultiServerMCPClient` | `infrastructure/mcp_clients/mcp_client_factory.py:59-62` | ✅ |
| No second/per-request MCP client | Single `build_mcp_client()` in `main.py` lifespan → `app.state.mcp_client` | ✅ |
| Static identity transport (typed args, not headers) | `search_messages(conversation_id, user_id, repo_id, ...)` | ✅ |
| Identity closure-bound for the LLM (`extra="forbid"` args_schema) | `ContextSearchQuery` in `context_agent_runtime.py` (§1, §9.5) | ✅ |
| Explicit tool list for Context Agent | `tool_lists.py`: `context_agent → {"conversation": {"search_messages"}}` | ✅ |
| Context Agent read-only | Only `search_messages` (SELECT-only) exists anywhere in its path | ✅ |
| No `execute_sql` tool | Conversation server exposes exactly one `@mcp.tool()` | ✅ |
| Audit on success and failure, no content/snippets | `SQLModelConversationAudit.record_context_invocation` | ✅ |
| FTS5 raw DDL in `init_db()` | `engine.py:_create_fts_index()` | ✅ |
| FTS5 phrase-quoting | `conversation_server.py:91-92` | ✅ |
| `tool_name_prefix` default False | `mcp_client_factory.py` (never set) | ✅ |

---

## 3. Final architecture

Phase 2 is intentionally stateless: a review receives the repository/review inputs, the Review Orchestrator routes work to specialist agents, and the Aggregator produces the review result. Phase 3 adds a persistent conversation layer **without changing** core review behavior when historical context is unavailable or unnecessary.

The central architectural change: conversation history is no longer an independent question-answering system. It is a **searchable evidence source for the Review Orchestrator**.

### 3.1 Architecture diagram

```text
                         HTTP / API Layer
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
          Conversation endpoints        POST /review
                 │                           │
                 ▼                           ▼
       Layer 3 Conversation Service   Review Orchestrator
                 │                     (DeepAgents)
                 │                           │
          persist messages                   │ conversation_id?
                 │                           │
                 ▼                           ▼
          SQLite conversation DB      scoped search_messages tool
                                             │
                                             ▼
                                  Conversation FastMCP Server
                                             │
                                   authorization + FTS5
                                             │
                                             ▼
                                      SQLite + FTS5
                                             │
                                             ▼
                                  historical evidence
                                             │
                                             ▼
                                  Review Orchestrator
                                             │
                         ┌───────────────────┴───────────────────┐
                         │                                       │
                  reason over evidence                    specialist delegation
                                                                 │
                                                                 ▼
                                                        Phase 2 review flow
```

### 3.2 Responsibility split

| Responsibility | Owner |
|---|---|
| Persist conversation | Layer 3 application + SQLite/SQLModel |
| Search messages | Conversation FastMCP + FTS5 |
| Authorize conversation access | Conversation MCP server (server-side) |
| Decide whether recall is useful | Review Orchestrator LLM |
| Interpret historical evidence | Review Orchestrator |
| Preserve provenance | MCP result (`message_id`) + orchestrator reasoning |
| Resolve conflicting historical facts | Orchestrator using recency |
| Review code | Existing Phase 2 specialists |
| Aggregate findings | Existing Phase 2 Aggregator |
| Summarize memory | **Phase 4 / LangMem** |
| Shared memory | **Phase 4** |
| Private memory | **Phase 4** |

### 3.3 Core principles

1. **`conversation_id` means availability, not mandatory recall.** A `conversation_id` on a review makes historical context *available*; it never forces a retrieval.

2. **The Review Orchestrator is the sole recall decision-maker.** There is no heuristic gate. The previous `should_recall()` marker/substring implementation is removed (`delegate_to_context_agent.py` deleted — must not be reintroduced under another name). Recall is a judgment made by the orchestrator's LLM from the conversation context and the review request.

3. **Context retrieval happens before specialist delegation when used.** This is a behavioral instruction in the orchestrator prompt, not a hard-coded application gate — the orchestrator must remain the authority over whether and when retrieval occurs.

4. **Retrieved data is evidence, not an answer.** `search_messages` returns evidence; `results[0]` is never treated as an answer. The orchestrator reasons over the complete returned evidence set, retains `message_id` provenance, and applies recency when historical statements contradict.

5. **The Context Agent is read-only and retrieval-only.** It is not an independent autonomous DeepAgents agent and has no independent LLM responsible for answering questions.

6. **Phase 2 behavior is unchanged without recall.** No `conversation_id` → the root orchestrator gets NO tools (Phase 2 behavior). `conversation_id` present but no recall → no context call, no context audit row.

---

## 4. End-to-end data flows

### 4.1 Review with historical context available

```text
POST /review
  │  repo_id, request_type, branch|graph_commit_hash, diff_content?,
  │  question?, conversation_id?, user_id?
  ▼
FastAPI review route (infrastructure/api/routes/review.py)
  │  ├─ validate request_type (400 on unknown)
  │  ├─ validate exactly one of branch | graph_commit_hash (400)
  │  ├─ require user_id when conversation_id is supplied (400)
  │  ├─ resolve branch → commit via GitHub MCP (404 if branch missing)
  │  ├─ prepare repository review context (404 unknown repo, 425 graph not ready)
  │  ├─ touch per-branch LRU recency (best-effort, never fails review)
  │  └─ create ReviewSession audit row (status=running)
  ▼
AgentInput (now carries conversation_id + user_id)
  ▼
Review Orchestrator / DeepAgents (run_review)
  │  ├─ root tools: conversation_id present → [audited search_messages tool]
  │  │              conversation_id absent → None (Phase 2 path)
  │  │              server down / tool absent → None (recall skipped,
  │  │                 AVAILABLE prompt block withheld too)
  │  ├─ classify/interpret request
  │  └─ LLM decides whether historical context is useful
  │        ├─ NO ─────────────────────────────► normal Phase 2 delegation
  │        └─ YES
  │             ▼
  │       search_messages(conversation_id, user_id, repo_id, query)
  │             ▼
  │       Conversation FastMCP: authz → FTS5 phrase-quote → MATCH → BM25
  │             ▼
  │       historical evidence (message_id, role, snippet, created_at, score)
  │             ▼
  │       audit wrapper (metadata only; no snippets/content)
  │             ▼
  │       Orchestrator reasons over full evidence, retains provenance,
  │       applies recency, then delegates specialists
  │             ▼
  │       Phase 2 specialists → Aggregator → review response
```

### 4.2 Conversation write / retrieval lifecycle

```text
POST /conversations
  │  {repo_id, user_id}
  ▼
SQLModelConversationRepository.create_conversation
  ▼
Conversation row (id, repo_id, user_id, status='active', timestamps)
  ▼
conversation_id returned

POST /conversations/{id}/message
  │  {user_id, repo_id, content}
  ▼
run_conversation_turn (application/conversation_service/)
  │  ├─ verify conversation exists (404 if not)
  │  ├─ next_order_index() = max order_index + 1  (monotonic)
  │  ├─ persist user Message (role=user, event_type=final)
  │  ├─ recall historical context via search_messages,
  │  │    exclude_message_id = the just-persisted message id
  │  ├─ if results: persist ToolCall row (tool_name=search_messages)
  │  │    with tool_input (query, truncated), tool_output (snippets), latency, status
  │  └─ audit context invocation (query/counts/latency/status only)
  ▼
Return {conversation_id, user_message, context (evidence), tool_calls}
  (NO assistant answer — answering is owned by the Review Orchestrator)
```

The old standalone `_synthesize_reply()` behavior is removed/deprecated. The conversation endpoint is a persistence/evidence surface; the Review Orchestrator owns review reasoning and answering.

---

## 5. Conversation database schema

The conversation layer uses the same SQLite database file as Phase 1/2 (`settings.metadata_db_path`). All ORM models live in `infrastructure/db/models.py`. Table names are **explicit PascalCase** (`__tablename__`) so the FTS5 external-content reference `content='Message'` and the exact PascalCase DDL requirement both hold. SQLModel's default (lowercased class name) would silently produce `message`/`conversation` and break `content='Message'` resolution.

### 5.1 Conversation

Stores the conversation identity and lifecycle.

| Field | Type | Constraints | Purpose |
|---|---|---|---|
| `id` | INTEGER | PK, autoincrement | Conversation identifier |
| `repo_id` | TEXT | NOT NULL | Repository scope |
| `user_id` | TEXT | NOT NULL | User scope |
| `status` | TEXT | NOT NULL DEFAULT 'active', CHECK `active`/`archived` | Lifecycle state |
| `created_at` | DATETIME | NOT NULL, server default UTC | Creation timestamp |
| `updated_at` | DATETIME | NOT NULL, server default UTC | Last-update timestamp |

Index: `idx_conversation_repo_user(repo_id, user_id)`.

### 5.2 Message

Stores searchable conversation events. `id` doubles as the provenance key the orchestrator retains.

| Field | Type | Constraints | Purpose |
|---|---|---|---|
| `id` | INTEGER | PK, autoincrement | Message identifier / provenance key |
| `conversation_id` | INTEGER | NOT NULL, FK → Conversation(id) ON DELETE CASCADE, indexed | Parent conversation |
| `role` | TEXT | NOT NULL, CHECK `user`/`assistant`/`system` | Message origin |
| `event_type` | TEXT | NOT NULL, CHECK `thinking`/`tool_use`/`final` | Event category |
| `content` | TEXT | NOT NULL | Searchable content |
| `order_index` | INTEGER | NOT NULL | Deterministic conversation ordering |
| `created_at` | DATETIME | NOT NULL, server default UTC | Temporal ordering |

Required constraint: `UNIQUE(conversation_id, order_index)` — prevents ambiguous conversation ordering. Monotonicity is guaranteed by `next_order_index()` (read `max(order_index)` + 1) in the same transaction context as the insert.

### 5.3 ToolCall

Stores tool-execution metadata associated with a message. **Not indexed by FTS5 in Phase 3 v1.**

| Field | Type | Purpose |
|---|---|---|
| `id` | INTEGER | Tool execution identifier |
| `message_id` | INTEGER | Parent Message (FK → Message(id) ON DELETE CASCADE, indexed) |
| `tool_name` | TEXT | Executed tool |
| `tool_input` | TEXT | Serialized input |
| `tool_output` | TEXT | Serialized output |
| `tool_latency_ms` | INTEGER | Execution duration |
| `tool_status` | TEXT | CHECK `success`/`error` |

### 5.4 MemorySummary

Schema exists for the planned Phase 4 memory phase. **In Phase 3 it is an implemented-but-unwired artifact**: the `summarize_conversation()` deterministic v1 use-case and the `ConversationStorePort.add_memory_summary()` adapter both exist, but **nothing in the active Phase 3 flow calls them**. It is neither populated by the turn flow nor queried by the Context Agent. It is deliberately kept in place as the Phase 4 LangMem replacement/summarization hook (see §20).

| Field | Type | Purpose |
|---|---|---|
| `id` | INTEGER | Summary identifier |
| `conversation_id` | INTEGER | Parent Conversation (FK → Conversation(id) ON DELETE CASCADE, indexed) |
| `summary_text` | TEXT | Summary content |
| `summarized_up_to_message_id` | INTEGER | High-water mark (FK → Message(id)) |
| `created_at` | DATETIME | Creation timestamp |

---

## 6. SQLite FTS5 search architecture

### 6.1 Why FTS5

Conversation recall requires lexical retrieval over stored message content without introducing another database service or vector-search infrastructure. Phase 3 deliberately avoids: PostgreSQL `tsvector`, `pgvector`, ChromaDB, embedding generation, generic RAG, and arbitrary SQL MCP tools.

### 6.2 Virtual table (raw DDL in `engine.py:_create_fts_index()`)

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    content,
    content='Message',
    content_rowid='id',
    tokenize = "porter unicode61 tokenchars '_-.'"
)
```

### 6.3 Tokenization

`porter unicode61` = basic stemming + Unicode-aware tokenization. `tokenchars '_-.'` preserves identifiers like `CLIP-4`, `snake_case_filename`, and `0.85` instead of shredding them. FTS5 remains lexical — no semantic similarity, no typo tolerance, no embeddings.

### 6.4 Synchronization triggers

Created in `init_db()` via the raw-DDL startup exception:

```text
INSERT Message ──► message_ai ──► insert into message_fts(rowid, content)
UPDATE Message ──► message_au ──► delete old row + insert new row
DELETE Message ──► message_ad ──► delete from message_fts
```

### 6.5 Search data flow

```text
Message.content
      ▼
SQLite trigger
      ▼
message_fts virtual table
      ▼
FTS5 MATCH (phrase-quoted query)
      ▼
BM25 ranking (−bm25() so higher = better)
      ▼
search_messages result
```

---

## 7. `search_messages` MCP contract

The Conversation FastMCP server (`infrastructure/mcp_clients/servers/conversation_server.py`) exposes **exactly one** Phase 3 tool:

```python
@mcp.tool()
async def search_messages(
    conversation_id: int,
    user_id: str,
    repo_id: str,
    query: str,
    limit: int = 10,
    exclude_message_id: int | None = None,
) -> str:
```

### 7.1 Inputs

| Parameter | Meaning |
|---|---|
| `conversation_id` | Conversation to search |
| `user_id` | Caller identity, used by the server-side authorization check |
| `repo_id` | Repository scope, used by the authorization check |
| `query` | Lexical search query |
| `limit` | Max result count, server-clamped to `1..25` |
| `exclude_message_id` | Optional message ID excluded from results; prevents a just-persisted user message from matching itself during a conversation turn |

### 7.2 Successful response

```json
{
  "conversation_id": 123,
  "results": [
    {"message_id": 42, "role": "user", "snippet": "...", "created_at": "2026-08-17T10:00:00Z", "score": 4.21}
  ]
}
```

`results` sorted best-match-first. `score` is higher-is-better because SQLite's raw BM25 score is negated: `-bm25(message_fts) AS score`. `snippet` uses `snippet(message_fts, 0, '[', ']', '...', 32)`.

### 7.3 Error semantics

| Case | Response |
|---|---|
| Unauthorized / nonexistent conversation | `{"conversation_id": N, "results": [], "error": "not_found"}` |
| Query > 200 chars, or FTS5 `OperationalError` | `{"conversation_id": N, "results": [], "error": "invalid_query"}` |

`not_found` and `invalid_query` must remain distinguishable — a malformed query must never be interpreted as "no historical information exists."

### 7.4 Limits

```text
MAX_SEARCH_RESULTS = 25
MAX_QUERY_LENGTH   = 200
```

`limit` is clamped to `max(1, min(limit, 25))`. Queries longer than 200 chars (after `.strip()`) return `invalid_query`. `sqlite3.OperationalError` from malformed FTS syntax is caught and converted to `invalid_query`.

### 7.5 Internal execution

1. **Authorization** (runs in a threadpool):
   ```sql
   SELECT 1 FROM Conversation WHERE id = ? AND user_id = ? AND repo_id = ?
   ```
   Missing row / identity mismatch → `not_found` (no existence leak).
2. **FTS5 query protection**:
   ```python
   clean_query = query.strip().replace('"', '""')
   fts_query = f'"{clean_query}"'
   ```
3. **Execution query**:
   ```sql
   SELECT m.id, m.role, snippet(message_fts, 0, '[', ']', '...', 32) AS snippet,
          m.created_at, -bm25(message_fts) AS score
   FROM message_fts f
   JOIN Message m ON f.rowid = m.id
   WHERE message_fts MATCH ? AND m.conversation_id = ?
   [AND m.id != ?]           -- when exclude_message_id is provided
   ORDER BY score DESC LIMIT ?
   ```

### 7.6 Threadpool offloading

`search_messages` is declared `async`; its synchronous core (`_search`, including the auth check and the SQLite read) runs via `fastapi.concurrency.run_in_threadpool` so the FastMCP event loop is never blocked. Each `_connect()` opens a fresh connection with `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`.

---

## 8. Security model

### 8.1 No arbitrary SQL

The Conversation MCP never exposes an `execute_sql` tool. The LLM can only invoke `search_messages(...)`. SQL is written and controlled by backend code.

### 8.2 Authorization

`conversation_id` is not an authorization boundary by itself. The Conversation MCP performs a server-side identity/scope check equivalent to:

```sql
SELECT 1 FROM Conversation WHERE id = :conversation_id AND user_id = :user_id AND repo_id = :repo_id;
```

If no matching row exists, the server returns `not_found` — identical for "conversation does not exist" and "conversation belongs to another user/repository." This prevents an existence/IDOR-style information leak.

### 8.3 Read-only Context Agent

The Context Agent cannot access database writes. Persistence is exclusively in the Layer 3 application flow (`run_conversation_turn`), never inside the Context Agent's path.

### 8.4 Network boundary

The Conversation FastMCP server is an internal service bound to `127.0.0.1` on port 9001 by default (`settings.conversation_mcp_url = "http://127.0.0.1:9001/mcp"`, bind host `127.0.0.1` unless `CONVERSATION_SERVER_HOST` is set). docker-compose runs it as its own `conversation-server` service bound to `0.0.0.0` so the `code-review-agent` container can reach it over the compose network (mirrors mcp-atlassian's `HOST` env). The security model never depends on an LLM-controlled identity value being trustworthy by itself — the server-side authorization check remains mandatory.

### 8.5 No raw snippets in audit logs

Audit records contain metadata only (`query`, `conversation_id`, `results_count`, `latency_ms`, `status`) — never retrieved message content or snippets.

---

## 9. Audit logging

Context retrieval uses the existing `ReviewSession` / `AgentExecution` audit pattern — no second logging system.

### 9.1 Row shape (`AgentExecution`)

| Column | Value |
|---|---|
| `review_session_id` | `None` for standalone turns; the active review session id when recall happens inside `POST /review` (nullable) |
| `conversation_id` | Target conversation id (optional FK, nullable) |
| `agent_name` | `"context_agent"` |
| `duration_ms` | Tool wall time |
| `result` | JSON via `json.dumps(dataclasses.asdict())` |

### 9.2 Audit payload (the `result` JSON)

```json
{
  "query": "...",
  "conversation_id": 123,
  "results_count": 4,
  "latency_ms": 18,
  "status": "ok"
}
```

`status` literal values: `"ok"` on success (note: **`"ok"`, not `"success"`**), `"not_found"` / `"invalid_query"` on those error responses, `"invalid_response"` on unparsable payloads. `"error:<ExceptionType>"` is recorded only by the turn flow's `_recall_context` failure path (a raised transport/session exception). The audited-tool path never reaches it: `handle_tool_error` captures a failing inner call as a `ToolMessage`, whose content then fails JSON parsing and records `"invalid_response"` instead (§9.4).

### 9.3 Strict privacy rule

Audit records must never contain: message content, snippets, full retrieved evidence, or tool output containing conversation text. The turn flow's `ToolCall` row is the only place snippets may persist, and it is a conversation-substrate row, not an audit row.

### 9.4 Coverage

- Successful context calls are audited.
- Failed context calls are audited (both the turn flow's `_recall_context` failure path and the tool-error path).
- `review_session_id` is populated for review-triggered retrieval; `None` for standalone turns.
- No-recall reviews produce **no** context audit row (no invocation occurred).

### 9.5 Identity security

The codebase has no auth middleware: identity is caller-supplied in the request body and transported as explicit typed arguments to `search_messages` (§1 Static Client Identity Transport, §8.2). The context-retrieval path never trusts an LLM-controlled identity value:

- **Turn flow** (`search_conversation_context`): identity is passed as explicit typed parameters — never derived from MCP headers or static client config.
- **Orchestrator audited tool** (`get_audited_context_tool`, §10.2): `conversation_id`/`user_id`/`repo_id` are closure-bound at construction time, before the LLM ever sees the tool. The LLM-visible `args_schema` is the narrow `ContextSearchQuery` model (`extra="forbid"`, exposing ONLY `query`/`limit`/`exclude_message_id`), so a hostile/injected call that tries to smuggle identity keys is REJECTED at schema validation (pydantic `ValidationError`) — never silently overridden downstream.
- **Server side**: the Conversation MCP re-checks `conversation_id + user_id + repo_id` on every call (§8.2), so the authorization boundary holds even if a caller reached `search_messages` directly.

---

## 10. Context Agent runtime

File: `infrastructure/agents_runtime/subagents/context_agent_runtime.py`.

The Context Agent is a **retrieval-only capability** implemented around the Conversation MCP `search_messages` tool. It is **not** a `deepagents.SubAgent` dict and not an autonomous reasoning loop — context recall is a single deterministic tool call, so the "runtime" is the scoped-tool accessor + audited wrapper the orchestrator uses.

```text
DeepAgents Review Orchestrator
             │
             │ tool available only when conversation_id exists
             ▼
    audited context retrieval tool
             │
             ▼
    Conversation FastMCP
             │
             ▼
      SQLite + FTS5
```

### 10.1 `get_search_messages_tool(mcp_client)`

Fetches `server_name="conversation"` tools from the shared client and scopes to exactly `{"search_messages"}` via `scoped()` (explicit named list — never a wildcard). Returns the single tool, or `None` if the tool is absent (server down / not registered) so callers can skip recall without failing the review.

### 10.2 `get_audited_context_tool(mcp_client, *, conversation_id, user_id, repo_id, audit, review_session_id, store)`

Builds the tool granted to the orchestrator root agent:

1. `scope_agent_tools(mcp_client, "context_agent", store)` — the event-wrapped (timeline-captured) scoped `search_messages` tool.
2. Wraps it with an audit wrapper that, per invocation: times the call, parses the JSON payload for `results_count`/`status`, and records one `AgentExecution` row through the injected `ConversationAuditPort` (query/counts/latency/status only — never content).
3. **Identity is closure-bound at construction time.** `conversation_id`/`user_id`/`repo_id` are injected server-side into every invocation; the LLM-visible `args_schema` is the narrow `ContextSearchQuery` model exposing ONLY `query`/`limit`/`exclude_message_id` with `extra="forbid"`. A hostile call that tries to supply identity keys is rejected at schema validation before the underlying tool runs — the LLM cannot choose, guess, or exfiltrate a scope.
4. Returns `None` when the tool is unavailable so the caller can skip recall without failing the review. A raised exception during tool build (Conversation server down / not registered — `scope_agent_tools` → `get_tools`) is caught, logged with its exception type (so unexpected build failures stay distinguishable from MCP-server unavailability), and converted to `None`.

### 10.3 `search_conversation_context(mcp_client, *, conversation_id, user_id, repo_id, query, limit, exclude_message_id)`

Invokes the scoped tool with explicit typed identity params. Returns the raw JSON string from the tool (or `None` when unavailable). Caller owns parsing + audit logging.

### 10.4 Read-only invariant

The Context Agent never writes: no write tool exists anywhere in its path, and it is strictly a historical-conversation retrieval component (no shared/private memory, no summarization).

---

## 11. Review Orchestrator integration

File: `infrastructure/agents_runtime/orchestrator_runtime.py`.

### 11.1 Root tool injection (`_build_root_tools`)

```text
conversation_id is None  ──► return None        (Phase 2 path: root gets NO tools)
conversation_id present  ──► build audited context tool
                                ├─ tool unavailable → return None (recall skipped)
                                └─ tool available  → return [audited_context_tool]
```

The distinction between `None` (no tools — Phase 2 byte-for-byte) and `[]` (tools withheld) is preserved. `deepagents` merges the `tools` argument additively with its built-in suite, so the root's `task` tool is preserved; the safety harness profile (`ensure_review_harness_profile`) still strips filesystem/execute built-ins.

### 11.2 Conversation context block (`_conversation_context_block`)

When `conversation_id` is present, the orchestrator's user message gains a "Historical conversation context is AVAILABLE" block. Identity (`conversation_id`/`user_id`/`repo_id`) is NOT declared — it is closure-bound into the tool at construction time (§10.2), so the block tells the LLM the tool is pre-scoped and instructs:

- call `search_messages` ONLY if historical context is needed — never on every request;
- do not pass `conversation_id`/`user_id`/`repo_id` — they are supplied server-side;
- if called, do so **BEFORE** delegating to subagents;
- treat results as evidence (reason over all of them, never answer from a single snippet);
- retain the `message_id` of every hit relied on;
- when recalled messages contradict, prefer the **most recent** one.

The block is absent when no conversation is supplied (Phase 2 prompt byte-for-byte). It is also omitted on the degraded path: when `conversation_id` is present but the tool could not be built (Conversation server down / not registered), `run_review` passes `context_available=False` and the block is withheld, so the model is never told it has a `search_messages` tool it was not granted.

### 11.3 Orchestrator prompt (`prompts/orchestrator.md`)

Defines: historical context is optional; the orchestrator decides whether to retrieve; retrieval occurs before delegation when needed; retrieved content is evidence with provenance, not conclusions; all evidence should be considered; `message_id` provenance must be retained; recency wins on conflict; no single result may automatically become the answer.

### 11.4 Aggregator prompt (`prompts/aggregator.md`)

Instruction 7: when the orchestrator consulted conversation history, it may cite evidence as `message #<id>` in a finding's evidence list. Those citations are first-class evidence, treated like `file:line` references; the message id is retained verbatim.

### 11.5 Audit wiring in reviews

The audited context tool is built with `SQLModelConversationAudit()` and the active `review_session_id`, so recall inside a review records `review_session_id` + `conversation_id` on the `AgentExecution` row.

---

## 12. Conversation turn flow

File: `application/conversation_service/run_conversation_turn.py`.

**PERSISTENCE + EVIDENCE-CAPTURE ONLY.** It does not generate an assistant answer. The Context Agent is a retrieval component; answering is owned by the Review Orchestrator (decisions D3/D4/D7).

### 12.1 Flow

1. `store.get_conversation(conversation_id)` — raise `ConversationNotFoundError` (→ HTTP 404) if missing.
2. `store.next_order_index(conversation_id)` — `max(order_index) + 1`, monotonic.
3. Persist the user `Message` (`role="user"`, `event_type="final"`, `order_index`, `created_at`).
4. Recall historical context (`_recall_context`): `search_context(..., exclude_message_id=user_message_row.id)` so the just-persisted message never matches itself. Recall is evidence-gathering — a failure is audited (`status="error:<Type>"`) and the turn continues without context.
5. If results exist, persist a `ToolCall` row (`tool_name="search_messages"`, `tool_input=query[:200]`, `tool_output=first-3 snippets joined ≤ 4000 chars`, `tool_latency_ms`, `tool_status="success"|"error"`).
6. Audit the context invocation (query/counts/latency/status).
7. Return `{conversation_id, user_message, context, tool_calls}`.

### 12.2 Threadpool boundary

Every synchronous SQLite call (`get_conversation`, `next_order_index`, `add_message`, `add_tool_call`) and the audit write run through `asyncio.to_thread`. The Context Agent call is async by nature (wire call).

### 12.3 MemorySummary — implemented but unwired (Phase 4 hook)

`application/conversation_service/summarize_conversation.py` provides a deterministic, dependency-free v1 summarizer (`summarize_conversation(conversation_id, *, store, recent_messages)` → persists a `MemorySummary` via `store.add_memory_summary()`). **Nothing calls it in Phase 3** — no route, no turn flow, no test. It is kept deliberately as the Phase 4 LangMem replacement point (an LLM summarizer can swap in behind the same `ConversationStorePort.add_memory_summary` port without touching the persistence layer). `MemorySummary` is NOT queried or ranked by the Context Agent, and must not be silently added to Phase 3 retrieval.

---

## 13. Updated folder architecture

```text
project-root/
│
├── domain/                              # Layer 4 — framework-free domain
│   └── entities/
│       ├── agent_finding.py             # AgentInput gains conversation_id/user_id
│       └── conversation_entity.py       # Conversation, Message, ToolCall, MemorySummary,
│                                        #   ContextRetrieval, ContextRetrievalResult, ConversationTurn
│
├── application/                         # Layer 3 — use cases/orchestration
│   └── conversation_service/
│       ├── ports.py                     # ConversationStorePort, ContextAgentPort, ConversationAuditPort
│       ├── run_conversation_turn.py     # persistence + evidence-oriented turn flow
│       └── summarize_conversation.py    # deterministic v1 MemorySummary (UNWIRED Phase 4 hook)
│
├── infrastructure/                     # Layer 5 — technical implementation
│   ├── api/
│   │   ├── models.py                    # ReviewRequest gains conversation_id/user_id
│   │   └── routes/
│   │       ├── conversation.py          # POST /conversations, POST /conversations/{id}/message
│   │       └── review.py                # 400 user_id rule, conversation_id/user_id → AgentInput
│   │
│   ├── db/
│   │   ├── models.py                    # Conversation, Message, ToolCall, MemorySummary (PascalCase)
│   │   ├── engine.py                    # init_db(): FTS5, triggers, migrations, PRAGMA foreign_keys=ON
│   │   ├── conversation_repository.py   # SQLModelConversationRepository = ConversationStorePort adapter (persistence)
│   │   └── conversation_ports_adapters.py  # McpContextAgent (ContextAgentPort/retrieval) +
│   │                                      #   SQLModelConversationAudit (ConversationAuditPort/audit)
│   │
│   ├── mcp_clients/
│   │   ├── mcp_client_factory.py        # shared MultiServerMCPClient, conversation = 5th server; scoped()
│   │   └── servers/
│   │       └── conversation_server.py   # FastMCP server: typed search_messages + server-side authorization
│   │
│   └── agents_runtime/
│       ├── orchestrator_runtime.py      # optional root context-tool injection
│       ├── tool_lists.py                # AGENT_TOOL_PLAN["context_agent"] = {"conversation": {"search_messages"}}
│       ├── prompts/
│       │   ├── orchestrator.md          # evidence/recall/provenance/recency instructions
│       │   └── aggregator.md            # message #<id> provenance acceptance
│       └── subagents/
│           └── context_agent_runtime.py # scoped + audited read-only context tool wrapper
│
└── tests/
    ├── test_conversation_phase3.py      # schema, FTS5, migration, authorization, turn flow
    └── test_context_agent_review_integration.py  # orchestrator↔context integration contract
```

### 13.1 Removed legacy module

```text
application/conversation_service/delegate_to_context_agent.py
```

Deleted. It contained the unused `should_recall()` heuristic and a separate delegation function that no longer matches the final architecture. `should_recall()` must **not** be reintroduced under another name — the Review Orchestrator is the sole recall decision-maker.

---

## 14. MCP registration and tool scoping

### 14.1 Shared client

One `MultiServerMCPClient` is constructed once at FastAPI startup (`app.state.mcp_client`) via `build_mcp_client()` in `main.py`'s lifespan. Phase 3 adds Conversation FastMCP as the 5th configured server:

```text
1. CRG         (streamable_http, settings.crg_server_url)
2. GitHub      (streamable_http, read-only headers: X-MCP-Readonly + X-MCP-Toolsets)
3. Atlassian   (streamable_http, settings.atlassian_mcp_url)
4. Context7    (streamable_http, https://mcp.context7.com/mcp)
5. Conversation (streamable_http, settings.conversation_mcp_url)
```

### 14.2 Tool scoping (`tool_lists.py`)

```python
CONVERSATION = {"context_agent": {"search_messages"}}

AGENT_TOOL_PLAN["context_agent"] = {"conversation": {"search_messages"}}
```

The Context Agent receives exactly `Conversation.search_messages` — never a wildcard, never a write tool. `scope_agent_tools()` (in `tool_scoping.py`) wraps each scoped tool with event-bus timeline capture (`_wrap_with_events`) and a 4000-char result truncation cap fed back to the model.

### 14.3 No per-request client

No second or per-request `MultiServerMCPClient` is created. The client is static at startup; identity flows as explicit typed tool arguments (see §1 Static Client Identity Transport).

---

## 15. Configuration and runtime wiring

### 15.1 Settings (`infrastructure/config.py`)

```python
conversation_mcp_url: str = "http://127.0.0.1:9001/mcp"
```

docker-compose overrides it to `http://conversation-server:9001/mcp` in the `code-review-agent` service. Never hardcode `127.0.0.1` in the client factory.

### 15.2 Conversation server launch

```text
python -m infrastructure.mcp_clients.servers.conversation_server
```

`_BIND_HOST` defaults to `127.0.0.1` for local dev; `CONVERSATION_SERVER_HOST=0.0.0.0` in docker-compose so the `code-review-agent` container can reach it. Port comes from `settings.conversation_mcp_url` (`_port_from_url`, default 9001). Transport is `streamable-http`, path `/mcp`.

### 15.3 docker-compose `conversation-server` service

```yaml
conversation-server:
  command: python -m infrastructure.mcp_clients.servers.conversation_server
  environment:
    - CONVERSATION_MCP_URL=http://127.0.0.1:9001/mcp
    - CONVERSATION_SERVER_HOST=0.0.0.0
  volumes: [workspace_data:/app/data]
  depends_on: [code-review-agent]
  restart: unless-stopped
```

### 15.4 Services required for Phase 3 work

```text
- code-review-graph serve --http --port 5555            (Phase 1)
- uvx mcp-atlassian --transport streamable-http --port 9000  (Phase 2)
- Conversation FastMCP server                           (Phase 3, port 9001)
```

---

## 16. Failure behavior and operational semantics

| Scenario | Behavior |
|---|---|
| Missing conversation context | Review proceeds through the existing Phase 2 path. Not an error. |
| Conversation available but recall unnecessary | Context tool available; orchestrator may not call it. No context audit row. |
| Unauthorized conversation | `not_found` for both nonexistent and unauthorized — no existence leak. |
| Invalid search query | `invalid_query` (overlong or FTS5 `OperationalError`). Never crashes the server; never interpreted as an empty historical result. |
| Context retrieval failure | Audited with failure status; the turn/review continues per existing error-handling policy. Never converts an error into a successful empty result; never invents evidence. |
| Conflicting historical messages | FTS5 score is not truth — the most recent message by `created_at`/`id` takes precedence (recency wins). |
| Conversation server down / tool absent | Orchestrator path: `get_audited_context_tool` catches the raised `get_tools` exception, logs it, and returns `None` — recall skipped, review proceeds (§10.2, §11.1). Turn flow: `get_search_messages_tool` propagates the raise, which `_recall_context` catches and audits as `error:<ExceptionType>`; the turn continues without context (§12.1). |

---

## 17. Concurrency and database execution

- `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=5000;` on every connection touching the conversation tables (engine connect listener + `conversation_server._connect()`).
- `PRAGMA foreign_keys=ON;` on every connection (engine connect listener + `conversation_server._connect()`).
- Synchronous SQLite in the FastAPI app runs via `asyncio.to_thread`.
- The FastMCP server's synchronous search core runs via `fastapi.concurrency.run_in_threadpool`.
- FastMCP calls use the application's existing MCP lifecycle — no per-request `MultiServerMCPClient`.

---

## 18. Request and response contracts

### 18.1 `ReviewRequest` (new fields)

```json
{
  "repo_id": "owner/repository",
  "request_type": "review",
  "branch": "feature/example",
  "graph_commit_hash": null,
  "diff_content": "...",
  "question": "...",
  "conversation_id": 123,
  "user_id": "user-42"
}
```

- `conversation_id` is optional.
- `conversation_id` supplied without `user_id` → HTTP 400 (`_validate_conversation_identity`).
- Values flow into `AgentInput.conversation_id` / `AgentInput.user_id`.

### 18.2 `CreateConversationRequest` / `MessageTurnRequest`

```text
POST /conversations              {repo_id, user_id}
POST /conversations/{id}/message {user_id, repo_id, content}
```

`MessageTurnRequest` includes `user_id`/`repo_id` so `search_messages`' authorization check can run (no auth middleware — identity is caller-supplied and authorized server-side).

### 18.3 `search_messages` request / response

See §7. Request and response JSON shapes are exact there.

---

## 19. Verification and test matrix

Tests live in `backend/src/code_review_agent/tests/`. `test_conversation_phase3.py` uses a dedicated temp SQLite engine (patched module-global engine during `init_db()`); `test_context_agent_review_integration.py` uses fake MCP clients / a recording audit port, no live LLM.

| # | Scenario | Expected | Coverage |
|---|---|---|---|
| 1 | Create conversation | Row with correct user/repo scope | unit (repository) |
| 2 | Persist message | Inserted with unique order index | ✅ `test_turn_persists_messages_and_audit` |
| 3 | Duplicate order index | DB rejects (UNIQUE) | ✅ `test_unique_order_index_enforced` |
| 4 | FTS insert | New Message searchable | ✅ `test_fts_phrase_quoting_hyphen` |
| 5 | FTS update | Updated content reflected | unit-untested (trigger code review) |
| 6 | FTS delete | Deleted Message removed | ✅ `test_foreign_keys_active_cascade` (cascade path) |
| 7 | `CLIP-4` search | Identifier searchable | ✅ `test_fts_phrase_quoting_hyphen` |
| 8 | `snake_case` search | Identifier searchable | unit-untested (tokenizer config verified in DDL) |
| 9 | Overlong query | `invalid_query` | ✅ `test_invalid_query_audited_gracefully` |
| 10 | Malformed FTS syntax | `invalid_query`, no exception | ✅ same (OperationalError path) |
| 11 | Wrong user | `not_found` | ✅ `test_search_messages_authorization_cross_tenant` |
| 12 | Wrong repository | `not_found` | ✅ same (cross-tenant) |
| 13 | Nonexistent conversation | `not_found` | ✅ `test_search_messages_authorization_cross_tenant` |
| 14 | Current-message exclusion | `exclude_message_id` honored | ✅ `test_search_messages_exclude_message_id`, `test_turn_tool_call_attaches_to_user_message_id` |
| 15 | Review without conversation_id | Phase 2 path: root has no tools | ✅ `test_no_conversation_id_grants_no_root_tools` |
| 16 | Review with conversation_id, no recall | No search call; no audit row | prompt-instructed (orchestrator decides) |
| 17 | Review with recall | Search before specialist delegation | prompt-instructed + `test_conversation_block_present_with_identity` |
| 18 | Evidence provenance | `message_id` retained in findings | ✅ prompt + aggregator `message #<id>` rule |
| 19 | Contradictory history | Most recent wins | prompt-instructed (recency rule) |
| 20 | Context call failure | Audited, no content logged | ✅ `test_invalid_query_audited_gracefully` |
| 21 | Context call success | Audited, no content logged | ✅ `test_audit_row_carries_session_and_conversation`; `assert "snippet" not in payload` |
| 22 | Conversation turn | Persistence/evidence result; no synthesized answer | ✅ `test_turn_persists_messages_and_audit` |
| 23 | Shared client | No second/per-request client | ✅ by construction (§14.3) |
| 24 | Tool scope | Context Agent sees only `search_messages` | ✅ `test_plan_entry_exactly_search_messages`, `test_conversation_id_grants_search_messages_only` |
| 25 | Conversation server down during tool build | Root gets no context tool; review proceeds | ✅ `test_tool_server_down_returns_none` |
| 26 | Hostile identity keys in tool call | Rejected at schema validation (`extra="forbid"`) | ✅ `test_hostile_identity_kwargs_rejected_at_validation` |
| 27 | LLM-visible schema scope | Exposes ONLY `query`/`limit`/`exclude_message_id`, no identity | ✅ `test_llm_visible_schema_exposes_no_identity` |
| 28 | Context tool withheld (server down) | AVAILABLE prompt block omitted | ✅ `test_context_available_false_omits_block` |

Live E2E (seeded fact → review cites it) is exercised separately against the running servers, not in unit tests.

---

## 20. Phase 3 → 4 handoff (for the Phase 4 architect)

Phase 3 intentionally creates the persistence and retrieval foundation the Phase 4 memory system must build on. The intended evolution:

```text
                         Phase 3
                           │
             ┌─────────────┴─────────────┐
             │                           │
      Conversation DB              Context retrieval
             │                           │
             └─────────────┬─────────────┘
                           │
                           ▼
                    Phase 4 memory phase
                           │
             ┌─────────────┼─────────────┐
             │             │             │
      Shared Memory   Private Memory   LangMem
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                    summarization
```

### 20.1 What Phase 4 must build

1. **LangMem shared memory for agents** — cross-conversation / persistent knowledge store.
2. **Private memory per agent** — each specialist agent gets its own private memory scope.
3. **Context-window-based summarization** — summarize messages when the **context window is almost full**, NOT after a fixed message count.

### 20.2 Existing substrate to consume (do not re-invent)

- `MemorySummary` table, `ConversationStorePort.add_memory_summary`, and `summarize_conversation.py` (deterministic v1) — the natural LangMem summarization replacement point behind the same port.
- `Message`/`ToolCall` persisted conversation history.
- `search_messages` retrieval boundary.

### 20.3 Boundaries that must be preserved (non-negotiable)

```text
LLM
 │
 ▼
controlled typed tool
 │
 ▼
server-side authorization
 │
 ▼
controlled data access
```

- The Context Agent stays read-only; no write tool is ever exposed to an LLM without explicit human confirmation outside its tool list.
- Memory writes happen in the application layer, never inside the Context Agent's path.
- Audit privacy rule extends to any new memory tables: never log content/snippets into `AgentExecution`.
- No second/per-request MCP client; no `execute_sql` tool; FTS5 phrase-quoting and server-side authorization remain.
- Shared/private memory and LangMem are Phase 4 scope; do not implement them speculatively in a later-phase file.

---

## 21. Definition of done (verified)

### Persistence
- [x] `Conversation`, `Message`, `ToolCall`, `MemorySummary` tables implemented (PascalCase `__tablename__`).
- [x] Foreign keys active (`PRAGMA foreign_keys=ON`).
- [x] `UNIQUE(conversation_id, order_index)` enforced.
- [x] `MemorySummary` schema retained; summarizer implemented-but-unwired (Phase 4 hook), not in the active Phase 3 flow.

### FTS5
- [x] `message_fts` created with `porter unicode61 tokenchars '_-.'`.
- [x] `message_ai` / `message_ad` / `message_au` sync triggers created in `init_db()`.
- [x] BM25 negated (higher-is-better).
- [x] Hyphenated identifiers tested (`CLIP-4`).

### Conversation MCP
- [x] Conversation FastMCP = 5th server in shared `MultiServerMCPClient`.
- [x] `search_messages` is the only exposed Phase 3 tool.
- [x] No `execute_sql` tool.
- [x] Authorization checks `conversation_id + user_id + repo_id` server-side.
- [x] `not_found` identical for unauthorized/nonexistent.
- [x] Query (`200`) and result (`25`) limits enforced; `invalid_query` on malformed/overlong.
- [x] `exclude_message_id` supported.

### Context Agent capability
- [x] Read-only; single tool.
- [x] No autonomous answer-generation loop.
- [x] `should_recall()` removed; Orchestrator is sole recall decision-maker.
- [x] Context tool injected at root only when `conversation_id` present.
- [x] Identity closure-bound (`extra="forbid"` args_schema) — hostile identity keys rejected at schema validation (§9.5).
- [x] Server-down resilience: tool-build failure caught + logged; recall skipped; review proceeds (§10.2, §16).
- [x] Evidence retains `message_id` provenance; `results[0]` never the answer; recency wins on contradiction.

### Review integration
- [x] `ReviewRequest` and `AgentInput` carry `conversation_id`/`user_id`.
- [x] 400 when `conversation_id` supplied without `user_id`.
- [x] Retrieval-before-delegation instruction in orchestrator prompt.
- [x] Phase 2 path unchanged without context (root gets no tools).
- [x] Degraded path: AVAILABLE prompt block omitted when the context tool was withheld (§11.2).
- [x] Aggregator accepts `message #<id>` provenance.

### Conversation turn
- [x] User messages persist; `exclude_message_id` prevents self-match.
- [x] ToolCall/evidence metadata persisted.
- [x] Standalone `_synthesize_reply()` removed.
- [x] Conversation endpoints remain as the persistent-history substrate.

### Audit and privacy
- [x] Context invocations audited on success and failure.
- [x] `review_session_id` nullable; populated for review-triggered calls.
- [x] Audit records contain no snippets/content.
- [x] No second/per-request MCP client.

### Future memory boundary
- [x] Shared Memory, Private Memory, LangMem, and summarization not activated in Phase 3.
- [x] Phase 4 can consume the persisted substrate without changing the Phase 3 retrieval contract.