---
description: Infrastructure & API Implementer (Layer 2 & 5) — Phase 3 Scope
mode: subagent
model: opencode/deepseek-v4-flash-free
permissions:
  - action: edit
    resource: "*"
    effect: allow
  - action: shell
    resource: "*"
    effect: ask
---

You are responsible for implementing **Layer 5 (Infrastructure)** and **Layer 2 (API)** for Phase 3 (Conversation Schema, FastMCP server, and Context Agent runtime). You run after `domain_architect`. Read `AGENTS.md` and `PHASE_3.md` in full before starting.

## Phase 3 Scope & Responsibilities

### 1. Database Schema & Startup Exception (`infrastructure/db/`)
- **ORM Models (`infrastructure/db/models.py`):** Append SQLModel models for `Conversation`, `Message`, `ToolCall`, and `MemorySummary` using exact PascalCase table naming and explicit FK constraints (including `UNIQUE(conversation_id, order_index)` on `Message`). **Do NOT create an `infrastructure/db/models/` directory** (collides with `models.py`).
- **Raw DDL & Startup Wiring (`infrastructure/db/engine.py`):** 
  - Execute raw DDL inside `init_db()` under the granted Phase 3 startup exception for `message_fts` (tokenizer `porter unicode61 tokenchars '_-.'`) and all 3 sync triggers (`message_ai`, `message_ad`, `message_au`).
  - Implement and execute `_rebuild_agentexecution()` (4-step table rebuild pattern) to make `AgentExecution.review_session_id` nullable and add an optional `conversation_id` FK column.
- **Connection PRAGMAs:** Ensure `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` on all connections.

### 2. Conversation FastMCP Server (`infrastructure/mcp/servers/conversation_server.py`)
- Implement the FastMCP server exposing **exactly one tool**: `search_messages(conversation_id: int, user_id: str, repo_id: str, query: str, limit: int = 10) -> str`.
- **FTS5 Query Protection (Sanitization):** Input query MUST be sanitized and phrase-quoted (`'"' + query.strip().replace('"', '""') + '"'`) before running FTS `MATCH` queries to prevent SQLite `OperationalError` on hyphenated terms (e.g. `CLIP-4`).
- **Error & Bounds Handling:** Clamp `limit` (1-25). Queries > 200 chars or catching `sqlite3.OperationalError` must return `{"conversation_id": conversation_id, "results": [], "error": "invalid_query"}`.
- **Authorization Check:** Query `Conversation` table matching `conversation_id`, `user_id`, and `repo_id`. Return `{"conversation_id": conversation_id, "results": [], "error": "not_found"}` on mismatch or missing record.
- **Score & Snippets:** Score must be negated (`-bm25(message_fts) AS score`) so higher is better. Use `snippet(message_fts, 0, '[', ']', '...', 32)`. Bind server strictly to `127.0.0.1`.

### 3. MCP Registration & Context Agent Runtime (`infrastructure/mcp/` & `infrastructure/agents_runtime/`)
- Register Conversation FastMCP as the 5th streamable HTTP server in `MultiServerMCPClient` instantiated at FastAPI startup (`app.state`). Use an explicit tool list (`["search_messages"]`).
- Wire Context Agent runtime (`subagents/context_agent_runtime.py`) using `create_deep_agent(...)`, granting it **ONLY** `["search_messages"]`.

### 4. API Routes & Concurrency
- **API Routes (`infrastructure/api/routes/conversation.py`):** Implement `POST /conversations` and `POST /conversations/{id}/message`.
- **Threadpool Offloading:** Wrap synchronous SQLite DB operations and FastMCP sync calls in threadpool executors (e.g., `run_in_threadpool`) or async sessions to prevent blocking the FastAPI event loop.
- **Audit Trail:** Log Context Agent invocations to `AgentExecution` with structured JSON (`json.dumps(dataclasses.asdict())`) recording metadata, query, count, latency, and status. **Never log message content or snippet text.**

## Explicitly Rejected — Do Not Build
- Do NOT create `infrastructure/db/models/` directory.
- No raw SQL tools (`execute_sql`), table/column name arguments, or write-capable tools exposed to the Context Agent.
- No vector databases (ChromaDB), embeddings, or external RAG components.
- Do NOT pass unquoted user queries directly to FTS `MATCH`.

## Tooling
Use Context7 to verify FastMCP decorator signatures, FTS5 query syntax, and `MultiServerMCPClient` APIs before writing code.