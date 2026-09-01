<div align="center">

<img src="frontend/public/favicon.svg" alt="ReviewMind logo" width="64" />

# ReviewMind

AI-Powered Code Intelligence Platform

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776ab?style=flat-square)](https://www.python.org)
[![React 18](https://img.shields.io/badge/React-18-61dafb?style=flat-square)](https://react.dev)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v3-06b6d4?style=flat-square)](https://tailwindcss.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

[Overview](#overview) &bull; [Architecture](#architecture) &bull; [Getting Started](#getting-started) &bull; [Configuration](#configuration) &bull; [API Reference](#api-reference) &bull; [Testing](#testing) &bull; [Limitations](#limitations)

</div>

---

## Overview

ReviewMind is a full-stack AI code review platform that orchestrates multiple specialized AI agents to analyze your codebase for security vulnerabilities, compliance issues, performance bottlenecks, and regression risks. It integrates directly with GitHub repositories via webhooks and provides a chat-based interface for asking questions about your code.

**Core capabilities:**

- **Multi-agent review** — 4 specialist agents (compliance, security, performance, regression) run in parallel against your code graph
- **7 request types** — Full review, targeted security/compliance/performance audits, impact analysis, code explanation, or open-ended questions
- **GitHub integration** — Webhook-driven sync, PAT-authenticated cloning, branch-aware graph analysis
- **Jira & Confluence** — Query issues and search documentation during reviews via MCP bridge
- **Conversation memory** — Full-text search across past conversations with FTS5-powered recall
- **Long-term memory** — Persistent agent memories across reviews via `langmem`
- **PWA frontend** — Dark-themed React interface installable as a desktop/mobile app with offline fallback
- **Account system** — Local identity with full account restoration from backend persistence

---

## Architecture

ReviewMind follows a **5-layer hexagonal architecture** on the backend with a **React + Vite + Tailwind** frontend.

```
┌─────────────────────────────────────────────────────────┐
│                     React PWA Frontend                   │
│            Vite dev proxy → /api/v1 → :8000              │
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────┐
│                   FastAPI (port 8000)                    │
│  16 endpoints across 5 routers (webhooks, review,       │
│  conversation, integrations, accounts)                   │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Domain        │  Layer 2: Application         │
│  entities, ports,       │  use-case services            │
│  routing policy         │  (review, conversation,       │
│                         │   repo ingestion, graph)      │
├─────────────────────────┴───────────────────────────────┤
│  Layer 5: Infrastructure                                │
│  ORM adapters, MCP clients, agent runtime, repo source  │
└───────────────────────────┬─────────────────────────────┘
                            │ MCP (streamable-http)
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   CRG (:5555)    GitHub MCP (remote)    Context7 (remote)
        ▼                   ▼                   ▼
   Atlassian MCP (:9000)        Conversation MCP (:9001)
```

### Backend layers

| Layer | Contents | Rules |
|---|---|---|
| **1 — Domain** | Entities, Protocol ports, routing policy | Zero framework imports |
| **2 — Application** | Use-case services (review, conversation, ingestion) | Async; depends only on Layer 1 ports |
| **5 — Infrastructure** | FastAPI routes, SQLModel adapters, MCP clients, agent runtime | Framework-dependent implementations |

### Multi-agent system

The orchestrator dispatches specialist agents based on request type:

| Request Type | Agents Dispatched |
|---|---|
| `review` | compliance, security, performance, regression |
| `security_question` | security |
| `compliance_question` | compliance |
| `performance_question` | performance |
| `impact_question` | regression |
| `explain_question` | _(orchestrator answers directly)_ |
| `any_question` | compliance, security, performance, regression |

Each agent receives scoped MCP tools (CRG graph, GitHub, Atlassian, Context7) plus shared and private memory tools. Tool calls are sanitized before persistence — GitHub PATs, Bearer tokens, and AWS keys are redacted.

### MCP servers

| Server | Port | Purpose |
|---|---|---|
| Code Review Graph (CRG) | 5555 | Code graph analysis, file/commit queries |
| GitHub MCP | remote | Read-only GitHub API (repos, PRs, code search) |
| Context7 | remote | Library documentation lookup |
| mcp-atlassian | 9000 | Jira issues + Confluence pages (read-only) |
| Conversation MCP | 9001 | FTS5 full-text search across conversation history |

### Code Review Graph (CRG)

CRG is a Tree-sitter-based tool that builds a **structural knowledge graph** of each registered repository, stored in SQLite and queried via MCP. The graph captures functions, classes, and files as nodes, with edges representing call relationships, imports, inheritance, and test coverage. It also computes community clusters, centrality metrics (hub/bridge nodes), and execution flows — giving review agents structural context beyond what raw file contents provide.

**Initial build:** When a repo is registered (`POST /repos`), a shallow clone is created and CRG runs `build_or_update_graph_tool(full_rebuild=True)` to analyze the entire codebase. The resulting graph is tied to a specific commit SHA and recorded as a `GraphSnapshot` with status `"ready"` or `"error"`.

**Incremental updates:** When a push webhook arrives on the default branch, CRG runs `build_or_update_graph_tool(full_rebuild=False, base=<last_indexed_commit>)`. It internally executes `git diff base..HEAD` to find changed files and incrementally updates only those parts of the graph — no full rebuild needed. This requires a `.git` history (shallow clones with `--depth 1` are sufficient since the diff base is tracked).

**Branch handling:** Each branch gets its own git worktree (a sibling directory of the base clone, e.g. `data/workspaces/my-repo__feature-x`). When a review is requested for a branch that hasn't been seen before, `EnsureBranchWorktreeService` creates the worktree and runs a full graph build. Subsequent reviews on the same branch trigger incremental updates. If a force-push makes the diff base unreachable, CRG falls back to a full rebuild automatically.

**Readiness gate:** Before any review runs, `GraphReadinessService` checks that a `GraphSnapshot` with `status="ready"` exists for the target commit. If not, the API returns HTTP 425 ("Graph not ready") and optionally triggers a background build. This is the "Preparing this branch..." state shown in the frontend.

---

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 18+
- Git
- Docker & Docker Compose (for containerized setup)
- A GitHub Personal Access Token (read-only scopes)
- An LLM provider API key (NVIDIA, OpenAI, Anthropic, Google, Groq, or OpenRouter)

### Docker Compose (recommended)

```bash
git clone https://github.com/mohamedborhen/code-review-agent.git
cd code-review-agent

# Create your .env from the template
cp .env.example .env
# Edit .env — set at minimum:
#   REVIEW_MODEL=nvidia:nvidia/nemotron-3-ultra-550b-a55b
#   NVIDIA_API_KEY=your-key
#   GITHUB_PAT=your-token
#   GITHUB_WEBHOOK_SECRET=any-random-string

docker compose up --build
```

This starts 4 services:

| Service | Port | Description |
|---|---|---|
| `code-review-agent` | 8000 | FastAPI backend |
| `crg-server` | 5555 | Code Review Graph MCP |
| `mcp-atlassian` | 9000 | Jira/Confluence bridge |
| `conversation-server` | 9001 | Conversation FTS5 search |

Frontend is served separately via Vite (see below).

### Local Development

Start all backend services first, then the frontend:

```bash
# Terminal 1 — CRG server
code-review-graph serve --http --port 5555

# Terminal 2 — Conversation MCP server
cd backend/src/code_review_agent
python -m infrastructure.mcp_clients.servers.conversation_server

# Terminal 3 — Atlassian MCP (optional, for Jira/Confluence)
uvx mcp-atlassian --transport streamable-http --port 9000

# Terminal 4 — FastAPI backend
cd backend/src/code_review_agent
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 5 — Frontend (Vite dev server with proxy)
cd frontend
npm install
npm run dev
```

The Vite dev server runs on `http://localhost:5173` and proxies `/api/v1` requests to `http://127.0.0.1:8000`.

> [!IMPORTANT]
> The backend startup fails hard if CRG is unreachable. Start CRG before the FastAPI app.

---

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure the required variables:

#### Required

| Variable | Description |
|---|---|
| `REVIEW_MODEL` | LLM model in `provider:model` format (e.g. `nvidia:nvidia/nemotron-3-ultra-550b-a55b`) |
| `GITHUB_PAT` | GitHub Personal Access Token (read-only) |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for webhook signature verification |
| `CRG_SERVER_URL` | CRG MCP endpoint (default: `http://127.0.0.1:5555/mcp`) |
| `WORKSPACE_ROOT` | Local clone storage path (default: `./data/workspaces`) |
| `METADATA_DB_PATH` | SQLite database path (default: `./data/phase1_metadata.db`) |
| `ATLASSIAN_MCP_URL` | Atlassian MCP endpoint (default: `http://127.0.0.1:9000/mcp`) |

#### LLM Provider (one required, matching `REVIEW_MODEL`)

| Variable | Provider |
|---|---|
| `NVIDIA_API_KEY` | NVIDIA AI Endpoints |
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Google Gemini |
| `GROQ_API_KEY` | Groq |
| `OPENROUTER_API_KEY` | OpenRouter |

#### Optional

| Variable | Description |
|---|---|
| `REVIEW_MAX_TOKENS` | Output token budget (default: 8192) |
| `REVIEW_TIMEOUT` | Per-call timeout in seconds (default: 600) |
| `CONTEXT7_API_KEY` | Context7 API key (public access if empty) |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key for credential vault (ephemeral if unset) |
| `CONVERSATION_MCP_URL` | Conversation MCP endpoint (default: `http://127.0.0.1:9001/mcp`) |

#### Atlassian (for Jira/Confluence integration)

| Variable | Description |
|---|---|
| `JIRA_URL` | Jira instance URL |
| `JIRA_USERNAME` | Jira username |
| `JIRA_API_TOKEN` | Jira API token |
| `CONFLUENCE_URL` | Confluence instance URL |
| `CONFLUENCE_USERNAME` | Confluence username |
| `CONFLUENCE_API_TOKEN` | Confluence API token |

The mcp-atlassian server also requires these runtime settings (set in `.env` or `docker-compose.yaml`):

```
READ_ONLY_MODE=true
ALLOW_GLOBAL_CRED_FALLBACK=true
TOOLSETS=all
ENABLED_TOOLS=jira_get_issue,confluence_search,confluence_get_page
```

### Credential Vault

Repository credentials (GitHub PAT, webhook secret, Jira tokens) are encrypted at rest using Fernet symmetric encryption and stored in the `RepoCredential` SQLite table. If `CREDENTIAL_ENCRYPTION_KEY` is not set, an ephemeral key is generated at startup — vault rows become unreadable after restart.

---

## API Reference

All endpoints are under `/api/v1`. The backend has **no CORS middleware** — the Vite dev proxy handles cross-origin requests during development.

### Webhooks & Repos

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/webhook` | Receive GitHub webhook events (HMAC-SHA256 verified) |
| `POST` | `/api/v1/repos` | Register a repo (stores encrypted credentials, triggers clone + graph build) |
| `GET` | `/api/v1/repos/{repo_id}/branches` | List all remote branches for a registered repo |

### Reviews

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/review` | Run a review (synchronous — blocks for entire duration) |
| `GET` | `/api/v1/reviews/running` | Find currently running review for a conversation |
| `GET` | `/api/v1/reviews/latest` | Find most recent review for a conversation |
| `GET` | `/api/v1/reviews/{session_id}` | Get review status, result, and tool-call metadata |

### Conversations

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/conversations` | Create a new conversation |
| `POST` | `/api/v1/conversations/{id}/message` | Persist user message + capture recall evidence |

### Integrations

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/integrations/jira` | Store encrypted per-user Jira credentials |
| `POST` | `/api/v1/integrations/jira/validate` | Probe Jira with supplied credentials (does not store) |

### Accounts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/accounts/lookup` | Verify a user_id exists; return counts |
| `GET` | `/api/v1/accounts/conversations` | List all conversations for a user |
| `GET` | `/api/v1/accounts/repos` | List all repos registered by a user |
| `GET` | `/api/v1/accounts/reviews` | List all review sessions for a user |
| `GET` | `/api/v1/accounts/conversations/{id}/messages` | Return interleaved user messages and reconstructed assistant results |

---

## Frontend

The frontend is a React 18 single-page application built with Vite, styled with Tailwind CSS v3, and configured as a PWA via `vite-plugin-pwa`.

### Tech Stack

| Technology | Role |
|---|---|
| React 18 | UI library |
| TypeScript 5 | Type safety |
| Vite 5 | Build tool & dev server |
| Tailwind CSS v3 | Utility-first styling (Material Design 3 token system) |
| react-router-dom v6 | Client-side routing |
| vite-plugin-pwa | Service worker, manifest, offline support |

### Pages

| Route | Page | Description |
|---|---|---|
| `/` | MainChat | Primary chat interface with message composer and review results |
| `/signin` | SignIn | Sign-in, account switch, account restore |
| `/onboarding` | Onboarding | Connect repo, webhook setup instructions, Jira configuration |
| `/settings` | Settings | Repo management, account card, PWA install, Jira status |

### Chat Flow

1. User types a message and selects a request type
2. **Call 1:** `POST /conversations/{id}/message` — persists the message and runs FTS5 recall
3. **Call 2:** `POST /review` — synchronous review that blocks for the full duration (observed: 186s–455s)
4. Live agent activity is shown via concurrent polling of `GET /reviews/running` and `GET /reviews/{id}`
5. Response is rendered with findings sorted by severity (critical → info)

### PWA

- **Offline fallback:** Navigating to an un-cached route shows `offline.html` with a retry button
- **Install:** Available via browser install prompt (Settings page shows install button)
- **Icons:** 192x192 and 512x512 PNG icons in `frontend/public/icons/`

---

## Identity & Account System

ReviewMind uses a **local, non-authenticated identity model**:

- Identity is a client-generated UUID v4 stored in `localStorage`
- Display names are optional user-provided labels (not stored in the database)
- The `user_id` is self-asserted in API requests — there are no auth tokens, sessions, or passwords
- Per-repo ownership is enforced server-side (409 on hijack attempts)

### Account Restoration

If you clear browser data or switch devices, you can restore your account:

1. Enter your Account ID (UUID) on the sign-in screen
2. The backend verifies the ID and returns conversation/repo/review counts
3. All conversations, repos, messages, and review history are synced to the new browser

> [!WARNING]
> Account restoration requires the original UUID. There is no password recovery mechanism. Store your Account ID securely.

### Legacy Data

Legacy `ReviewSession` records with `user_id=NULL` and `conversation_id=NULL` may exist from pre-account-system runs. These are orphaned and excluded from account restoration.

---

## Persistence

### SQLite Tables

| Table | Purpose |
|---|---|
| `RepoWorkspace` | Registered repo metadata, branch, local path, last sync |
| `GraphSnapshot` | CRG build status per repo/commit |
| `ReviewSession` | Review runs with status, timing, agent dispatch info |
| `AgentExecution` | Per-agent execution results within a review |
| `Conversation` | Chat conversations (repo_id, user_id, status) |
| `Message` | User messages only (role='user'); assistant results reconstructed from AgentExecution |
| `ToolCall` | Conversation-level Context Agent tool calls |
| `ReviewToolCall` | Review-level agent tool calls (feeds the EventFeed UI) |
| `MemorySummary` | Conversation summaries for context compression |
| `RepoCredential` | Encrypted vault for GitHub PAT, webhook secret, Jira tokens |

### FTS5 Full-Text Search

A `message_fts` virtual table indexes conversation messages using the `porter unicode61` tokenizer with support for hyphenated identifiers (e.g. `CLIP-4`). Search queries are phrase-quoted to prevent SQL injection.

---

## Testing

```bash
# Backend unit tests (267 tests)
cd backend/src/code_review_agent
pytest

# Frontend build check
cd frontend
npm run build

# Frontend type check
cd frontend
npx tsc --noEmit
```

### E2E Verification Status

All 17 features verified via Playwright MCP automation:

- First-time sign-in, account restore, account switching
- Repo registration (409 conflict correct), repo restoration
- Branch loading and selection
- Compliance question flow, full review flow
- Conversation creation, switching, and persistence
- Loading/spinner state, error state, empty state
- PWA install section, responsive/mobile layout
- Request type dropdown (7 options), Settings page

---

## Limitations

> [!CAUTION]
> ReviewMind is a **research prototype**, not a production system.

- **No authentication** — Identity is self-asserted. Any client can impersonate any `user_id`. There are no auth tokens, session management, or access controls beyond per-repo ownership checks.
- **No CORS middleware** — The backend has no CORS configuration. The Vite dev proxy is the only mechanism for cross-origin access. Production deployment requires adding CORS middleware or a reverse proxy.
- **Synchronous reviews** — `POST /review` blocks for the entire review duration (2–8+ minutes). There is no async job queue, progress WebSocket, or background processing.
- **Single-user MCP servers** — mcp-atlassian uses a single global credential set. Per-user Jira credentials are stored but only injected at the MCP client level, not passed to the mcp-atlassian process.
- **SQLite only** — No PostgreSQL, no connection pooling, no replication. Suitable for single-instance development and demonstration.
- **No webhook auto-registration** — Webhooks must be configured manually in GitHub. The frontend provides instructions but cannot create webhooks via API.
- **Local storage only** — Account data, conversations, and messages are stored in browser `localStorage`. Clearing browser data loses local state (restorable via account restore if the backend is running).
- **NVIDIA provider intermittently unreachable** — The default LLM provider has occasional availability issues. Retry middleware handles transient failures.
- **Graph not ready (425)** — When a repo is first registered, the code graph takes time to build. Reviews return HTTP 425 until the graph is ready.
- **No rate limiting** — No request throttling or quota management on any endpoint.
