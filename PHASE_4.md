# Phase 4 — Short-Term Summarization, Durable Conversation Summaries, Shared Memory, Private Memory (LangMem)

**Status:** Specification — ready for implementation. Written for an implementing agent to build without guessing.
**Phase:** 4
**Predecessors:** Phase 1 (Ingestion & Knowledge Graph Pipeline), Phase 2 (Stateless Multi-Agent Review Core), Phase 3 (Conversation Persistence, Conversation FastMCP, Context Retrieval).
**Primary goal:** (a) fix the prerequisite tool audit truncation bug in `tool_scoping.py`, (b) make in-context summarization trigger off an explicit token-budget calculation for `nvidia:nvidia/nemotron-3-ultra-550b-a55b` (262,144 context window), (c) fulfill Phase 3's contract by wiring durable conversation summaries into `MemorySummary` via `ConversationStorePort.add_memory_summary()`, and (d) give agents long-term memory — one store shared across all agents per user/repo, and one private scope per agent — using standard LangMem primitives.
**Explicit scope discipline:** this is meant to be a *simple, standard* LangMem integration. Nowhere in this document should you build a custom summarization algorithm, a custom memory-scoping engine, or a new MCP server. If a step below looks like it's asking for custom infrastructure, stop — that's a sign the step was misread, not a sign to improvise.

---

## 0. Prerequisite & How to use this document

### 0.1 Prerequisite Bug Fix (PHASE-4 TOP PRIORITY)

Before writing any Phase 4 memory or summarization code, resolve the known audit-logging bug in `tool_scoping.py`. The event-wrapper in `tool_scoping.py` currently truncates tool results at 4,000 characters. This causes `get_audited_context_tool`'s audit logging to misreport large-but-successful recalls as `invalid_response`/`results_count=0`. Fix this truncation limit so that memory recall and search events do not misreport as phantom failures in audit logs during Phase 4 development.

### 0.2 Verification Standard

Every factual claim about `deepagents`, `langmem`, and `langgraph` APIs below was verified against their actual source/docs via Context7 before being written down — none of it is from training-data memory of these libraries, because that memory is not reliable enough for a "no guessing" spec. Where something could not be verified without running the actual pinned versions in this repo, it's called out explicitly in §9 (Open Questions) rather than asserted as fact. Treat §9 the same way prior phase docs in this project treat their open-questions sections: resolve before merging the affected part, don't infer an answer.

---

## 1. The three memory pillars in Phase 4

Phase 4 implements three distinct memory and summarization mechanisms that solve different problems. They are not competing; they run alongside each other:

1. **`deepagents` already ships built-in, token-based, non-fixed-count in-context summarization.** As of `deepagents` v0.7.0+, `create_deep_agent()` automatically appends a `SummarizationMiddleware` to every agent it builds — the same `create_deep_agent()` call this project's orchestrator already uses. This keeps a single active agent execution from overflowing the model's token budget by trimming in-flight messages in the LangGraph checkpoint state.
2. **Durable Conversation Summarization (Phase 3 Contract).** Phase 3 §20.2 explicitly built `application/conversation_service/summarize_conversation.py` and `ConversationStorePort.add_memory_summary()` as a placeholder contract for Phase 4. Unlike in-context summarization (which is ephemeral to a run), this mechanism generates a durable summary at the end of a review run and persists it into the `MemorySummary` SQLModel table.
3. **Long-Term Agent Memory (`langmem`).** Long-term memory (shared + private) is a separate, genuinely new piece — using standard `langmem` primitives to allow agents to store and search facts across sessions, scoped by `{user_id}` and `{repo_id}`.

---

## 2. Non-negotiable compliance constraints

Carried forward from Phase 1–3, still in force:

* **5-layer clean architecture.** No new domain-layer code in this phase imports `fastapi`, `deepagents`, `langchain_mcp_adapters`, `langmem`, `pydantic`, `sqlmodel`, or any store/checkpoint class. (This phase, unlike Phase 3, is not expected to need new domain entities at all — see §7.)
* **No second/per-request client or store constructed ad hoc.** Exactly one `BaseStore` instance is constructed once at FastAPI startup (mirroring `app.state.mcp_client` from Phase 3) and reused everywhere. Do not call `SqliteStore.from_conn_string(...)` more than once in the running process.
* **SQLite concurrency settings apply to every new connection touching shared state**: `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `PRAGMA foreign_keys=ON` — same rule as Phase 1–3, extended to whatever connection the memory store opens (§6.3 spells out exactly how, since `SqliteStore` doesn't apply these by default).
* **SQLite is permanent — no Postgres.** LangMem's own docs default to recommending `PostgresStore`/`AsyncPostgresStore` for production. Do not follow that recommendation. This project's storage decision was already made and is not being revisited here (see the Phase 3 spec's resolved open item on this). §6.3 specifies the SQLite-backed alternative.
* **No semantic/embedding search.** This project has rejected vector/embedding-based retrieval twice already — Phase 1's core hypothesis was that graph-based representation outperforms embedding-based RAG, and Phase 3 §6.1 explicitly lists "no embeddings" as a deliberate constraint for conversation search. LangMem's memory tools *can* do semantic search via an `index` config on the store — **do not configure it**. §6.4 covers what this means concretely and what's given up by skipping it.
* **Async/sync boundary discipline** — same rule as Phase 1–3: synchronous SQLite persistence calls from async code go through the threadpool-offload pattern (`asyncio.to_thread` / `fastapi.concurrency.run_in_threadpool`). The LangMem memory store is the one deliberate exception: langmem's memory tools execute their async variants inside deepagents' async graph and call `await store.aput`/`asearch` directly, so the store MUST be async — §6.3 uses `AsyncSqliteStore`, which ships at `langgraph.store.sqlite` (the sync `SqliteStore` raises `NotImplementedError` on async operations, so it is not an option here).
* **Tool exposure follows the existing per-agent scoping discipline** — but not through the same mechanism as Phase 3. `AGENT_TOOL_PLAN`/`scope_agent_tools()` (Phase 2/3) scope tools that come from `MultiServerMCPClient`'s MCP servers. LangMem's memory tools are plain LangChain tools constructed directly in Python — they never go through an MCP server, so they are never added to `AGENT_TOOL_PLAN`. Keep these two tool-provisioning paths conceptually separate; don't try to route LangMem tools through the MCP scoping system, and don't try to route MCP tools through LangMem's namespace mechanism.
* **Identity flows the same way it was fixed to flow in Phase 3.** Phase 3's security fix established that identity (`user_id`/`repo_id`/`conversation_id`) must be bound by trusted Layer 3 code via `config.configurable`, never left as an LLM-fillable tool argument. §6.2 shows why LangMem's namespace-templating mechanism is actually a *cleaner* fit for that same rule than the MCP tool-argument approach was — but it still needs to be wired correctly, not assumed.
* **Identity source (acknowledged, unchanged):** `user_id`/`repo_id` remain caller-supplied tenant-scope keys — the OPENCODE.md Auth + User-table PENDING QUESTION is not resolved by this phase and no `User` table or auth middleware is introduced. Phase 4 keeps binding identity via `config.configurable` exactly as §6.2 specifies; a productized identity source is deferred to the spec that addresses that blocker.
* **Dependency Requirement:** `langchain-nvidia-ai-endpoints`, `langmem`, and `langgraph-checkpoint-sqlite` must be explicitly listed in `requirements.txt` (`aiosqlite`/`sqlite-vec` arrive transitively via `langgraph-checkpoint-sqlite`).
* **Write-capable tool exception, scoped and flagged.** Phase 3 §20.3 states: "no write tool is ever exposed to an LLM without explicit human confirmation outside its tool list." LangMem's `manage_memory` tool is, by design, an LLM-autonomous write tool — that's the entire point of agent memory. This phase is a deliberate, bounded exception to that rule, not a violation of it — but it must stay bounded. The exception applies *only* to the memory namespaces this phase creates. It grants no write access to `Conversation`/`Message`/`ToolCall`/`MemorySummary` or any other existing table, and no other write-capable tool gets added anywhere else as a side effect of this phase. Flag this exception explicitly when this phase is reviewed — don't let it pass silently just because it's "standard" LangMem behavior.

---

## 3. Scope — what Phase 4 is and is not

**In scope:**

* Prerequisite: Fixing the `tool_scoping.py` 4000-char result truncation bug for audit logging.
* Explicitly configuring deepagents' built-in in-context summarization for `nvidia:nvidia/nemotron-3-ultra-550b-a55b` using an explicit 222,822 token trigger budget (85% of 262,144).
* Wiring Phase 3's `ConversationStorePort.add_memory_summary()` and `summarize_conversation.py` to persist durable conversation summaries into `MemorySummary` at review run completion.
* One shared long-term memory scope, readable/writable by every agent in a given conversation, scoped by `{user_id}` and `{repo_id}`.
* One private long-term memory scope per subagent, readable/writable only by that subagent, scoped by `{user_id}`, `{repo_id}`, and the literal subagent name.
* The store backend those live in (SQLite-backed, per the project's standing decision).
* Wiring identity into memory namespaces safely via `config.configurable`, consistent with Phase 3's security posture.
* Adding `langchain-nvidia-ai-endpoints` to `requirements.txt`.

**Explicitly not in scope — do not build these now:**

* Semantic/embedding-based memory search (§2, §6.4).
* A new MCP server (memory tools are native LangChain tools, not MCP tools — see §2).
* Cross-repo shared memory (e.g. memory shared across different repositories for the same user). Shared memory is scoped per-user AND per-repo (`("{user_id}", "{repo_id}")`) to avoid cross-repo memory bleed.
* Any change to Phase 3's `search_messages`, the Conversation FastMCP server, or the Context Agent. This phase adds memory mechanisms alongside Phase 3's conversation-history search — it does not modify or replace it.

---

## 4. Architecture overview

```text
                    DeepAgents Review Orchestrator (create_deep_agent)
                                      │
                 ┌────────────────────┼────────────────────┐
                 │                    │                     │
      SummarizationMiddleware   root agent tools      subagent tools
      (explicit token budget    ┌─────┴─────┐         ┌─────┴─────┐
       222,822 / 262,144)       │  shared    │         │  private  │
                 │              │  memory    │         │  memory   │
                 │              │  tool(s)   │         │  tool(s)  │
                 │              │  (all      │         │  (this    │
                 │              │  agents)   │         │  agent    │
                 │              └─────┬──────┘         │  only)    │
                 │                    │                 └─────┬─────┘
                 ▼                    ▼                        ▼
        trims/summarizes      create_manage_memory_tool /  create_manage_memory_tool /
        in-context messages   create_search_memory_tool    create_search_memory_tool
        when token budget      namespace=("memories",       namespace=("memories",
        reaches 222,822 tokens "shared", "{user_id}",       "private", "{user_id}", "{repo_id}",
                 │             "{repo_id}")                 "<agent_name literal>")
                 │                    │                         │
                 ▼                    └────────────┬────────────┘
        (operates on LangGraph                     ▼
         checkpointer state,              Single BaseStore
         not the memory store)            (AsyncSqliteStore, same
                 │                        metadata_db_path file)
                 │
                 ▼
    End of orchestration review run:
    ConversationStorePort.add_memory_summary()
    (Durable conversation history summary saved to MemorySummary table)

```

Three complementary mechanisms:

1. **Short-term (in-context) summarization** — operates on the LangGraph *checkpointer* (conversation turn state), not the memory store. Built into `deepagents`, token-budget-triggered (222,822 tokens). Ephemeral.
2. **Durable conversation summarization** — operates at the end of a review run, generating an LLM summary of the session and persisting it via `ConversationStorePort.add_memory_summary()` into `MemorySummary`.
3. **Long-term memory** — operates on the LangGraph *store*, namespace-scoped per user and repo (shared) and per user, repo, and subagent (private). Persisted in `SqliteStore`.

---

## 5. Summarization (In-Context & Durable)

### 5.1 What's built into deepagents & the NVIDIA Nemotron reality

Confirmed directly from `deepagents`' source (`deepagents/graph.py`, `deepagents/middleware/summarization.py`):

```python
# deepagents/graph.py — this already runs inside create_deep_agent() today
deepagent_middleware.extend([
    create_summarization_middleware(model, backend),
    PatchToolCallsMiddleware(),
])

```

```python
# deepagents/middleware/summarization.py
def compute_summarization_defaults(model: BaseChatModel) -> SummarizationDefaults:
    has_profile = (
        model.profile is not None
        and isinstance(model.profile, dict)
        and "max_input_tokens" in model.profile
        and isinstance(model.profile["max_input_tokens"], int)
    )
    if has_profile:
        return {
            "trigger": ("fraction", 0.85),
            "keep": ("fraction", 0.10),
            "truncate_args_settings": {"trigger": ("fraction", 0.85), "keep": ("fraction", 0.10)},
        }
    return {
        "trigger": ("tokens", 170000),
        "keep": ("messages", 6),
        "truncate_args_settings": {"trigger": ("messages", 20), "keep": ("messages", 20)},
    }

```

**Model-specific facts for this project:**

* The configured `REVIEW_MODEL` is `nvidia:nvidia/nemotron-3-ultra-550b-a55b` (using `ChatNVIDIA`).
* Runtime inspection confirms `model.profile` is `{}` and does not contain `max_input_tokens`, because this exact model string is not present in LangChain NVIDIA's static model-profile registry.
* Model context window: NVIDIA NIM documentation specifies a native context window of **262,144 tokens (256K)** for this endpoint.
* Model spec string: `nvidia:nvidia/nemotron-3-ultra-550b-a55b` contains only one `:` (`provider:model_path`). It safely avoids the `deepagents` `_get_harness_profile` multi-colon crash bug (`spec.count(':') > 1`).

Because `model.profile` is `{}` (unpopulated), `deepagents` auto-detection falls back to its flat 170,000-token fallback. Therefore, Phase 4 must **not rely on auto-detection** and must explicitly configure the 262,144-token window calculations.

### 5.2 Explicit SummarizationMiddleware Configuration

Before placing middleware code, inspect existing project structure (`infrastructure/agents_runtime/middleware.py` and `capture.py`) to confirm established placement patterns.

Construct `SummarizationMiddleware` explicitly using explicit token thresholds derived from the 262,144 token window:

* **Trigger threshold:** 85% of 262,144 = **222,822 tokens**.
* **Keep threshold:** 10% of 262,144 = **26,214 tokens**.

```python
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain_core.messages.utils import count_tokens_approximately

summarization_middleware = SummarizationMiddleware(
    model=review_model,          # the SAME model object used to build the orchestrator
    backend=review_backend,      # the SAME backend object passed to create_deep_agent()
    trigger=("tokens", 222822),
    keep=("tokens", 26214),
    token_counter=count_tokens_approximately,
)

```

**Backend requirement:** the project's `create_deep_agent` call currently passes no `backend` (deepagents defaults to `StateBackend()`). To satisfy "the SAME backend object", construct `backend = StateBackend()` once (`from deepagents.backends.state import StateBackend`) and pass `backend=backend` to BOTH `create_deep_agent(...)` and this `SummarizationMiddleware(..., backend=backend)`. Update `create_deep_agent` accordingly — do not leave it at its internal default, or the middleware and the agent would use different backend objects.

### 5.3 Durable Conversation Summarization (Phase 3 Contract)

Phase 3 built `ConversationStorePort.add_memory_summary()` and `summarize_conversation.py` as an explicit port for persistent summaries. Phase 4 fulfills the contract and upgrades the summarizer:

* At the conclusion of an orchestrator review run (as a post-orchestration step in `orchestrator_runtime.py` after `run_review` resolves successfully), invoke `summarize_conversation.py` with an injected **LLM summarizer** that calls `settings.review_model` with a short "summarize this review session" prompt over the plain-text run of messages since the last summary (sourced from `ConversationStorePort.list_messages()`).
* The LLM call must be fault-tolerant: on timeout/provider error, fall back to the deterministic tail-summary v1 already in the module — a memory-summary failure must never fail the review.
* Save the resulting summary via `ConversationStorePort.add_memory_summary()`, writing a new row to the `MemorySummary` SQLModel table.
* This creates durable historical context across sessions without interfering with `SummarizationMiddleware`'s in-context message trimming.

### 5.4 Required verification steps

1. Inspect existing `infrastructure/agents_runtime/middleware.py` and `capture.py` before adding middleware definitions.
2. Confirm the pinned `deepagents` version is ≥ 0.7.0.
3. Confirm how `create_deep_agent(middleware=[...])` composes with its internal middleware list. Verify by compiling the graph and checking node list to ensure there is **exactly one** summarization node (preventing double-summarization).

---

## 6. Long-term memory — shared and private

### 6.1 The two LangMem tool factories

Confirmed from `langmem`'s source (`langmem/knowledge/tools.py`) and docs:

```python
from langmem import create_manage_memory_tool, create_search_memory_tool

create_manage_memory_tool(
    namespace: tuple[str, ...] | str,
    *,
    instructions: str = "...",     # default instructs the agent to proactively store facts — fine to keep as-is for v1
    schema: type = str,
    actions_permitted: tuple[Literal["create","update","delete"], ...] | None = ("create","update","delete"),
    store: BaseStore | None = None,
    name: str = "manage_memory",
)

create_search_memory_tool(
    namespace: tuple[str, ...] | str,
    *,
    store: BaseStore | None = None,
    name: str = "search_memory",
)

```

Both tools resolve their `store` from the graph's runtime automatically when the graph was compiled with a `store=` argument (i.e. `create_deep_agent(..., store=my_store)`). `deepagents.create_deep_agent()` forwards `checkpointer` and `store` straight through to LangChain's `create_agent()` unchanged — pass `store=` once to `create_deep_agent(...)`, and any LangMem tool given to the root agent or a subagent will resolve it automatically.

### 6.2 Namespace design — user and repo scoping

There's no separate "shared memory API" and "private memory API" in LangMem — both are the same tool factories, differentiated by the `namespace` tuple passed at tool-construction time. `{placeholder}` segments are resolved from `config={"configurable": {...}}` at `.invoke()`/`.ainvoke()` time. **This is a LangGraph runtime mechanism, not a tool-call argument the LLM fills in.**

To prevent "memory bleed" across repositories while allowing user preferences and repo architecture facts to persist across sessions, memory is scoped by both `{user_id}` and `{repo_id}`:

**Shared memory** — one tool pair, given to the root orchestrator and every subagent:

```python
create_manage_memory_tool(namespace=("memories", "shared", "{user_id}", "{repo_id}"))
create_search_memory_tool(namespace=("memories", "shared", "{user_id}", "{repo_id}"))

```

**Private memory** — one tool pair *per subagent*, with the agent's own name baked in as a literal:

```python
# Security subagent:
create_manage_memory_tool(namespace=("memories", "private", "{user_id}", "{repo_id}", "security"))
create_search_memory_tool(namespace=("memories", "private", "{user_id}", "{repo_id}", "security"))

# Performance subagent:
create_manage_memory_tool(namespace=("memories", "private", "{user_id}", "{repo_id}", "performance"))
create_search_memory_tool(namespace=("memories", "private", "{user_id}", "{repo_id}", "performance"))

```

Build each subagent's private tool pair alongside wherever that subagent's other tools are already assembled — do not add these to `AGENT_TOOL_PLAN` (§2); add them directly to each subagent's `tools=[...]` at construction time.

`user_id` and `repo_id` must be supplied via `config={"configurable": {"user_id": ..., "repo_id": ...}}` at the point `graph.ainvoke(...)` is called in `orchestrator_runtime.py`, sourced from trusted `AgentInput` values.

### 6.3 Store backend: `SqliteStore`, same file, PRAGMA settings applied manually

Confirmed from `langgraph-checkpoint-sqlite` 3.1.1's source: `AsyncSqliteStore` and `SqliteStore` both exist at `langgraph.store.sqlite` (from `langgraph/store/sqlite/aio.py` and `base.py`). Use `AsyncSqliteStore`: langmem's memory tools run their async variants inside deepagents' async graph and call `await store.aput`/`asearch`, which the sync `SqliteStore` does not support (`abatch` raises `NotImplementedError`).

Use the same `settings.metadata_db_path` file already used by every other table in this project. The connection is constructed manually so the standing PRAGMAs are applied (neither store applies them by default):

```python
import aiosqlite
from langgraph.store.sqlite import AsyncSqliteStore

conn = await aiosqlite.connect(settings.metadata_db_path, isolation_level=None)
await conn.execute("PRAGMA journal_mode=WAL")
await conn.execute("PRAGMA busy_timeout=5000")
await conn.execute("PRAGMA foreign_keys=ON")
memory_store = AsyncSqliteStore(conn)   # no index config — see §6.4
await memory_store.setup()              # idempotent; safe to await once at startup

```

Build this once at FastAPI startup as `app.state.memory_store` — inside the async `lifespan` (the constructor captures `asyncio.get_running_loop()`, so it cannot be built at module import) — and pass it into `create_deep_agent(store=app.state.memory_store)`. Do not construct a second store anywhere else in the process.

### 6.4 No embedding index — what this costs, explicitly

`SqliteStore(conn)` above is constructed **without** an `index` config. Search within a namespace returns items without relevance ranking by meaning. This is a deliberate trade-off matching this project's anti-embedding stance (§2).

### 6.5 What data actually gets stored

A memory `Item` stored via `manage_memory` looks like:

```python
Item(
    namespace=["memories", "shared", "user-456", "repo-789"],
    key="<uuid>",
    value={"content": '{"action":"create","content":"the team decided to use WAL mode for the conversation DB"}'},
    created_at="...",
    updated_at="...",
    score=None,
)

```

Nothing here requires a new domain entity in `domain/entities/`. Do not invent a `MemoryEntity` dataclass unless a concrete need shows up.

---

## 7. Folder architecture (additions to Phase 3's tree)

```text
project-root/
│
├── requirements.txt                   # MODIFIED — add langchain-nvidia-ai-endpoints,
│                                       #   langmem, langgraph-checkpoint-sqlite
│
├── application/
│   └── conversation_service/
│       # MODIFIED — summarize_conversation.py gains an injected LLM summarizer (§5.3)
│
├── infrastructure/
│   ├── config.py                      # add explicit summarization trigger/keep constants
│   │
│   ├── agents_runtime/
│   │   ├── memory_store.py            # NEW — build_memory_store(): constructs the single SqliteStore
│   │   │                              #   with PRAGMAs applied (§6.3), returns it for main.py's lifespan
│   │   ├── memory_tools.py            # NEW — build_shared_memory_tools(), build_private_memory_tools(agent_name)
│   │   │                              #   (§6.2) — pure tool-construction, no business logic
│   │   ├── middleware.py / capture.py # INSPECT/MODIFIED — check existing middleware structure before placing
│   │   │                              #   SummarizationMiddleware definitions
│   │   ├── orchestrator_runtime.py    # MODIFIED — construct SummarizationMiddleware explicitly (§5.2),
│   │   │                              #   pass store= to create_deep_agent, attach shared memory tools to
│   │   │                              #   root, pass user_id/repo_id via config.configurable at invoke time,
│   │   │                              #   wire durable conversation summary via ConversationStorePort
│   │   └── subagents/                 # subagent tools get private memory tools attached directly
│   │
│   └── api/
│       └── main.py                    # MODIFIED — lifespan constructs memory_store once,
│                                       #   sets app.state.memory_store, calls store.setup()
│
└── tests/
    └── test_memory_phase4.py          # NEW — tests namespace isolation (shared vs private, user/repo scope),
                                        #   summarization trigger at 222,822 tokens, store reuses metadata_db_path,
                                        #   only one SqliteStore/one summarization node exists

```

---

## 8. Definition of done

* [ ] **Prerequisite fixed:** `tool_scoping.py` 4000-char truncation limit removed/fixed for audit logging so memory recall events do not misreport as invalid.
* [ ] `langchain-nvidia-ai-endpoints` added to `requirements.txt`.
* [ ] Inspected `middleware.py` and `capture.py` before adding new middleware logic.
* [ ] `SummarizationMiddleware` explicitly configured with `trigger=("tokens", 222822)` (85% of 262,144) and `keep=("tokens", 26214)`. Confirmed exactly one summarization node exists in compiled graph.
* [ ] Durable conversation summarization wired: `summarize_conversation.py` called at review run completion with an injected LLM summarizer (`settings.review_model`, deterministic fallback on failure), persisting via `ConversationStorePort.add_memory_summary()` into `MemorySummary`.
* [ ] `AsyncSqliteStore` import path confirmed against installed `langgraph-checkpoint-sqlite` (§6.3). Single instance constructed once in the async startup lifespan with manual PRAGMAs applied, stored on `app.state.memory_store`; `await store.setup()` runs once.
* [ ] Shared memory tools attached to orchestrator and subagents, namespace `("memories", "shared", "{user_id}", "{repo_id}")`.
* [ ] Private memory tools attached per-subagent, namespace `("memories", "private", "{user_id}", "{repo_id}", "<literal agent name>")`, confirmed via test that Security cannot read Performance's memory.
* [ ] `user_id` and `repo_id` supplied via `config={"configurable": {...}}` at `graph.ainvoke(...)` call sites, sourced from trusted `AgentInput`.
* [ ] No `index`/embedding config on the store (§6.4).
* [ ] Write-capable nature of `manage_memory` explicitly flagged and acknowledged as a scoped exception (§2).

---

## 9. Open questions — all resolved by package inspection before implementation

| # | Question | Status |
| --- | --- | --- |
| 1 | Does `create_deep_agent(middleware=[...])` replace or add to its own auto-built `SummarizationMiddleware`? | **RESOLVED — replaces.** `deepagents.graph._apply_custom_middleware` merges by `.name`; the explicit `SummarizationMiddleware` and the auto-added one both report `name == "SummarizationMiddleware"` (verified on 0.7.1), so the explicit instance replaces the auto one in place → exactly one summarization node. |
| 2 | Is the pinned `deepagents` version ≥0.7.0? | **RESOLVED — yes, 0.7.1 installed.** |
| 3 | Exact import path for `SqliteStore` (`langgraph.store.sqlite`) — and confirm sync-wrapping behavior. | **RESOLVED — use `AsyncSqliteStore` from `langgraph.store.sqlite`.** langmem tools call async store methods (`aput`/`asearch`) in the async graph; sync `SqliteStore.abatch` raises `NotImplementedError` (verified `base.py:1480`). |
| 4 | Does `store.setup()`'s internal schema collide with any existing table name in `metadata_db_path`? | **RESOLVED — no collision.** Creates `store` (+ optional `store_vectors`, only with index config) and `store_migrations` (async variant). No overlap with existing `RepoWorkspace`/`GraphSnapshot`/`ReviewSession`/`AgentExecution`/`Conversation`/`Message`/`ToolCall`/`MemorySummary`/`message_fts`. |
| 5 | Exact default `name`/signature for `create_search_memory_tool`. | **RESOLVED — `(namespace, *, instructions=..., store=None, response_format="content", name="search_memory")`** (verified langmem 0.0.30 `tools.py:361`). §6.1's keyword usage is valid. |

---

## 10. Documentation references

* LangMem — memory tools guide: [https://langchain-ai.github.io/langmem/guides/memory_tools/](https://langchain-ai.github.io/langmem/guides/memory_tools/)
* LangMem — dynamic namespace configuration (the `{user_id}`-style templating this doc's §6.2 relies on): [https://langchain-ai.github.io/langmem/guides/dynamically_configure_namespaces/](https://langchain-ai.github.io/langmem/guides/dynamically_configure_namespaces/)
* LangMem — summarization guide: [https://langchain-ai.github.io/langmem/guides/summarization/](https://www.google.com/search?q=https://langchain-ai.github.io/langmem/guides/summarization/)
* LangMem — short-term memory API reference: [https://langchain-ai.github.io/langmem/reference/short_term/](https://langchain-ai.github.io/langmem/reference/short_term/)
* LangMem — repository: [https://github.com/langchain-ai/langmem](https://github.com/langchain-ai/langmem)
* LangGraph — `BaseStore` reference: [https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint/langgraph/store/base/**init**.py](https://www.google.com/search?q=https%3A%2F%2Fgithub.com%2Flangchain-ai%2Flanggraph%2Fblob%2Fmain%2Flibs%2Fcheckpoint%2Flanggraph%2Fstore%2Fbase%2F__init__.py)
* LangGraph — SQLite checkpoint/store package: [https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-sqlite](https://www.google.com/search?q=https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-sqlite)
* `deepagents` — source of `create_deep_agent`, `SummarizationMiddleware`: [https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py](https://www.google.com/search?q=https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py)
* `deepagents` — package docs: [https://langchain-ai.github.io/deepagents/](https://www.google.com/search?q=https://langchain-ai.github.io/deepagents/)