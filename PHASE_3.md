```markdown
# Phase 3 Implementation Spec — Conversation Schema, Conversation FastMCP, Context Agent

**Status:** Ready to build (Phase 3)  
**Scope:** New stateful capability, additive to Phase 1 (Ingestion & Knowledge Graph Pipeline) and Phase 2 (Stateless Multi-Agent Review Core). Extends existing persistence, API layer, and agent orchestrator to support stateful conversation lifecycle and context recall.

---

## 0. How to use this document

This is a build contract, not a suggestion. If something you need is not written down here, **do not infer it, do not default to a "reasonable" choice, and do not copy a pattern from an unrelated framework.** Stop and surface the gap as a question in `OPENCODE.md` instead of writing code around it. Section 9 documents the explicit resolutions to all architectural questions surfaced during the pre-flight audit.

Before writing any code that touches FastMCP or SQLite FTS5 syntax, verify the exact API via the Context7 MCP tool, per the project's existing library-verification rule. Do not write MCP server/tool decorator code from memory.

---

## 1. Non-negotiable compliance constraints

These come directly from the existing Phase 1/2 architecture and pre-flight audit resolutions:

- **5-layer clean architecture is mandatory.** Domain layer (Layer 4) code for this feature (`domain/entities/`) must contain zero imports of `fastapi`, `deepagents`, `langchain_mcp_adapters`, `pydantic`, `git`/`subprocess`, `mcp`, or `sqlmodel` — same rule already enforced on `AgentFinding`/`AgentOutput`.
- **File Placement Discipline.** ORM models must be appended to the existing `infrastructure/db/models.py` file (not a `models/` directory, which collides with the existing module). Application services belong under `application/conversation_service/`.
- **Sync/Async execution boundaries.** FastMCP tool invocations and SQLite transactions must not block the FastAPI event loop. Synchronous SQLite persistence calls must be wrapped in threadpool executors (e.g., using `run_in_threadpool`) or use explicit async sessions to match strict concurrency rules.
- **SQLite concurrency settings must match Phase 1**: `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` on every connection that touches the new tables.
- **MCP registration must follow the existing `MultiServerMCPClient` lifespan pattern.** The new Conversation FastMCP server is a 5th streamable HTTP server added to the static client instantiated at FastAPI startup (`app.state`). Do not create a second or per-request MCP client.
- **Static Client Identity Transport.** Because `MultiServerMCPClient` headers are static per-server configs set once at startup, dynamic identity attributes (`user_id`, `repo_id`) are passed as explicit typed arguments to `search_messages` and populated by Layer 3 Application orchestration from the API request body. There is no auth middleware in the codebase (deferred in Phase 1) — `POST /conversations` and `POST /conversations/{id}/message` must accept `user_id` and `repo_id` in the request body, and the Layer 3 orchestrator forwards them verbatim into `search_messages`, where the §5.1 authorization check runs.
- **Explicit tool lists only.** The Conversation MCP must register a named, minimal tool list (`["search_messages"]`) — never a wildcard.
- **The Context Agent is read-only, full stop.** Mirror the Fix Suggestion agent's precedent: the Context Agent may only ever be given search/read tools. No tool that can INSERT, UPDATE, or DELETE conversation data is ever exposed to it.
- **No `execute_sql`-style tool, ever.** Every tool this MCP exposes must be a rigid, typed Python function.
- **Audit discipline matches `ReviewSession`/`AgentExecution`.** Context Agent invocations must be logged with structured output (`json.dumps(dataclasses.asdict())`) and must log on failure too, not just success.
- **Startup Wiring Exception.** An explicit, documented exception is granted in `infrastructure/db/engine.py` to execute raw DDL for FTS5 tables (`message_fts`) and triggers during `init_db()`.

---

## 2. Database schema (exact DDL & migrations)

### 2.1 Core Tables (`infrastructure/db/models.py`)

Append these SQLModel definitions to `infrastructure/db/models.py` using PascalCase table naming:

```sql
CREATE TABLE Conversation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id    TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
    created_at DATETIME NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at DATETIME NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_conversation_repo_user ON Conversation(repo_id, user_id);

CREATE TABLE Message (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES Conversation(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    event_type      TEXT NOT NULL CHECK (event_type IN ('thinking','tool_use','final')),
    content         TEXT NOT NULL,
    order_index     INTEGER NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(conversation_id, order_index)
);
CREATE INDEX idx_message_conversation_id ON Message(conversation_id);

CREATE TABLE ToolCall (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER NOT NULL REFERENCES Message(id) ON DELETE CASCADE,
    tool_name       TEXT NOT NULL,
    tool_input      TEXT,
    tool_output     TEXT,
    tool_latency_ms INTEGER,
    tool_status     TEXT CHECK (tool_status IN ('success','error'))
);
CREATE INDEX idx_tool_call_message_id ON ToolCall(message_id);

CREATE TABLE MemorySummary (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id              INTEGER NOT NULL REFERENCES Conversation(id) ON DELETE CASCADE,
    summary_text                 TEXT NOT NULL,
    summarized_up_to_message_id  INTEGER NOT NULL REFERENCES Message(id),
    created_at                   DATETIME NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_memory_summary_conversation_id ON MemorySummary(conversation_id);

```

Field types, nullability, and constraints above are final. `UNIQUE(conversation_id, order_index)` is required to enforce deterministic conversation ordering.

### 2.2 FTS5 Index & Triggers (`infrastructure/db/engine.py`)

Executed via raw SQL inside `init_db()` in `infrastructure/db/engine.py`:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    content,
    content='Message',
    content_rowid='id',
    tokenize = "porter unicode61 tokenchars '_-.'"
);

CREATE TRIGGER IF NOT EXISTS message_ai AFTER INSERT ON Message BEGIN
    INSERT INTO message_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS message_ad AFTER DELETE ON Message BEGIN
    INSERT INTO message_fts(message_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS message_au AFTER UPDATE ON Message BEGIN
    INSERT INTO message_fts(message_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO message_fts(rowid, content) VALUES (new.id, new.content);
END;

```

`porter unicode61 tokenchars '_-.'` is required so identifiers like `CLIP-4` or `snake_case_filename` are not shredded.

### 2.3 Table Rebuild Script for `AgentExecution`

Implement `_rebuild_agentexecution()` in `infrastructure/db/engine.py` (following the established `_rebuild_repoworkspace` 4-step pattern) to alter `review_session_id` from `NOT NULL` to `NULLABLE` and add an optional `conversation_id` FK:

1. Create `agentexecution_temp` with `review_session_id INTEGER NULL REFERENCES ReviewSession(id)` and `conversation_id INTEGER NULL REFERENCES Conversation(id)`. The temp table must include **all** existing `AgentExecution` columns (`agent_name`, `duration_ms`, `confidence`, `model`, `result`, `created_at`, plus the two FK columns) so the copy in step 2 preserves every column — follow the full-schema `_rebuild_repoworkspace` 4-step pattern, not just the FK columns shown here.
2. Copy existing records from `AgentExecution` into `agentexecution_temp`.
3. Drop table `AgentExecution`.
4. Rename `agentexecution_temp` to `AgentExecution`.

---

## 3. Layer placement & Repository Structure

Place all Phase 3 files strictly in the exact repository paths established in Phase 1/2:

* **Layer 4 (Domain):** `domain/entities/conversation_entity.py` — framework-free dataclasses mirroring `AgentFinding`/`AgentOutput`.
* **Layer 5 (Infrastructure):**
* `infrastructure/db/models.py` — SQLModel ORM models for `Conversation`, `Message`, `ToolCall`, `MemorySummary`.
* `infrastructure/db/engine.py` — `init_db()` extensions for raw FTS5 DDL and `_rebuild_agentexecution()`.
* `infrastructure/mcp_clients/servers/conversation_server.py` — FastMCP server implementation.
* `infrastructure/mcp_clients/mcp_client_factory.py` — Registration of Conversation FastMCP as 5th server.
* `infrastructure/agents_runtime/subagents/context_agent_runtime.py` — Context Agent runtime setup.
* `infrastructure/api/routes/conversation.py` — Endpoints for stateful turns (`POST /conversations` and `POST /conversations/{id}/message`), accepting `user_id` and `repo_id` in the request body (no auth middleware exists; identity is caller-supplied and authorized inside `search_messages`).


* **Layer 3 (Application):** `application/conversation_service/` — `run_conversation_turn.py`, `delegate_to_context_agent.py`, and summarization pipelines.

---

## 4. Write Path & Persistence Lifecycle

Because the Context Agent and its toolset are strictly read-only, all persistence operations for the new schema occur in the Orchestrator/Application layer outside the Context Agent's execution loop:

* **Message and ToolCall Writes:** New `Message` and `ToolCall` rows are inserted by the Application layer (`application/conversation_service/`) during an active conversation turn (`POST /conversations/{id}/message`). These writes must be wrapped in explicit transaction boundaries to guarantee `order_index` monotonicity and rollback safety on failure.
* **MemorySummary Writes:** `MemorySummary` generation and database insertion is triggered asynchronously or strictly at the end of a conversation turn by a dedicated summarizer service, never by the read-only Context Agent.

---

## 5. Conversation FastMCP — tool contract

Exactly one tool for Phase 3:

```python
MAX_SEARCH_RESULTS = 25
MAX_QUERY_LENGTH = 200

@mcp.tool()
def search_messages(
    conversation_id: int,
    user_id: str,
    repo_id: str,
    query: str,
    limit: int = 10
) -> str:
    """
    Returns a JSON string:
    {
      "conversation_id": int,
      "results": [
        {"message_id": int, "role": str, "snippet": str, "created_at": str, "score": float}
      ]
    }
    `results` is sorted best-match-first. `score` is normalized so that
    HIGHER means a better match (negate SQLite's raw bm25(): `-bm25(message_fts) AS score`).

    Error responses:
    {"conversation_id": int, "results": [], "error": "not_found"}
      — conversation does not exist or user_id/repo_id authorization check fails.
    {"conversation_id": int, "results": [], "error": "invalid_query"}
      — query exceeds MAX_QUERY_LENGTH or causes an FTS5 syntax operational error.
    """

```

### 5.1 Internal Tool Execution & FTS5 Phrase Quoting

1. **Mandatory Authorization Check:**
Execute `SELECT 1 FROM Conversation WHERE id = :conversation_id AND user_id = :user_id AND repo_id = :repo_id`. On missing row or identity mismatch, return `{"conversation_id": conversation_id, "results": [], "error": "not_found"}` to prevent IDOR access without leaking existence.
2. **FTS5 Query Protection (Sanitization):**
To prevent unhandled `OperationalError` when searching terms containing hyphens or operators (e.g. `CLIP-4`), query strings MUST be sanitized and wrapped in phrase quotes before passing to SQLite:
```python
clean_query = query.strip().replace('"', '""')
fts_query = f'"{clean_query}"'

```


3. **Execution Query:**
```sql
SELECT m.id, m.role, snippet(message_fts, 0, '[', ']', '...', 32) AS snippet,
       m.created_at, -bm25(message_fts) AS score
FROM message_fts f
JOIN Message m ON f.rowid = m.id
WHERE message_fts MATCH :fts_query AND m.conversation_id = :conversation_id
ORDER BY score DESC
LIMIT :clamped_limit;

```


4. **Limits & Error Handling:**
* `limit` is clamped server-side to `1 <= limit <= MAX_SEARCH_RESULTS`.
* Query strings exceeding `MAX_QUERY_LENGTH` or throwing `sqlite3.OperationalError` must return `{"conversation_id": conversation_id, "results": [], "error": "invalid_query"}`.



---

## 6. Context Agent

* Additive subagent built in `infrastructure/agents_runtime/subagents/context_agent_runtime.py`, given **only** the `search_messages` tool.
* Triggered by the Layer 3 Application layer when historical conversation context is missing or referenced by the user.
* Retrieved results are evidence, not conclusions. The Orchestrator must retain `message_id` provenance.
* **Default Precedence Rules:**
* `search_messages` results outrank `MemorySummary` content.
* For contradicting messages across turns, the most recent message by `created_at`/`id` supersedes.



---

## 7. Audit logging

Extend the existing `ReviewSession`/`AgentExecution` audit pattern to cover Context Agent invocations:

* `review_session_id`: `None` (optional/nullable).
* `conversation_id`: Target conversation ID.
* `agent_name`: `"context_agent"`.
* `result`: Structured JSON string via `json.dumps(dataclasses.asdict())` recording `query`, `conversation_id`, `results_count`, `latency_ms`, and `status`.
* **Strict Privacy Rule:** Explicitly **do not** log returned message content or snippet text in the audit tables.

---

## 8. Explicit "do not" list

* Do not add a tool that accepts raw SQL, a table name, or a column name.
* Do not expose any write-capable tool (INSERT/UPDATE/DELETE) to the Context Agent.
* Do not add vector/embedding search, ChromaDB, or any external RAG component.
* Do not skip the FTS5 sync triggers.
* Do not let the "not found" vs "not yours" authorization responses differ.
* Do not return raw `bm25()` values as `score` without negating them.
* Do not pass unquoted user queries directly into FTS `MATCH` statements (must phrase-quote to handle hyphens like `CLIP-4`).
* Do not let a malformed FTS5 query raise an unhandled exception.
* Do not create a `models/` directory alongside `models.py`.
* Do not instantiate a second `MultiServerMCPClient` or per-request MCP clients.

---

## 9. Architectural Decisions & Resolutions

| # | Topic | Decision / Resolution |
| --- | --- | --- |
| 1 | Database Location | Uses the same SQLite `.db` file as Phase 1/2 (`RepoWorkspace`/`ReviewSession`). |
| 2 | FTS Scope | Includes `Message.content` only. `ToolCall.tool_input`/`tool_output` are excluded from FTS v1. |
| 3 | Memory Summary Precedence | `search_messages` exact matches outrank `MemorySummary`. `MemorySummary` serves as general background. |
| 4 | Network Binding & Port | FastMCP server binds to `127.0.0.1` on an unused internal port configured via `settings.conversation_mcp_url` (default `http://127.0.0.1:9001/mcp`). |
| 5 | Identity Transport | Explicit `user_id` and `repo_id` typed parameters passed to `search_messages`, populated by Layer 3 orchestration. |
| 6 | Database Migration | `AgentExecution.review_session_id` made nullable via `_rebuild_agentexecution()` 4-step table rebuild helper in `engine.py`. |
| 7 | Contradiction Policy | Recency wins: most recent message by `created_at`/`id` supersedes historical ones. |
| 8 | Privacy in Auditing | Query strings logged; returned text snippets and message contents redacted from audit logs. |

---

## 10. Definition of done

* [ ] `AgentExecution` table rebuilt via `_rebuild_agentexecution()` with nullable `review_session_id` and optional `conversation_id`.
* [ ] All four tables created with exact PascalCase DDL in `infrastructure/db/models.py`, FK constraints active.
* [ ] `message_fts` + all three sync triggers created in `infrastructure/db/engine.py` via `init_db()` startup exception.
* [ ] WAL mode + `busy_timeout=5000` confirmed active across all DB connections.
* [ ] Threadpool/Async execution boundaries enforced for SQLite/FastMCP operations.
* [ ] Write path explicitly defined and isolated to Layer 3 `application/conversation_service/` logic.
* [ ] `search_messages` implemented as the **only** tool on the Conversation FastMCP server.
* [ ] FTS5 query phrase-quoting implemented and verified against hyphenated search strings (`CLIP-4`).
* [ ] Authorization check implemented and verified via cross-tenant test (`user_id`/`repo_id` validation).
* [ ] Context Agent runtime created with strict read-only access to `search_messages`.
* [ ] Context Agent invocations logged via `AgentExecution` without logging content/snippets.
* [ ] Domain-layer entities (`domain/entities/conversation_entity.py`) contain zero disallowed framework imports.
* [ ] `UNIQUE(conversation_id, order_index)` constraint present and tested against duplicate order inserts.
* [ ] FTS5 `tokenchars '_-.'` configured and tested with identifier strings.
* [ ] `score` field confirmed higher-is-better (`-bm25(...)`).
* [ ] `limit` and `query` length bounds enforced server-side.

```

```