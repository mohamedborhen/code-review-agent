# PHASE_5_FRONTEND.md — ReviewMind Frontend Build Contract

Companion to the Stitch design export. Give OpenCode **all** of it: this
file, the five Stitch-exported HTML/CSS (Tailwind) screen files, the five
matching PNGs, and `reviewmind/DESIGN.md`.

**The export is the visual source of truth, HTML and PNG together.** The
HTML is authoritative for structure, class names, and design tokens; the PNG
is authoritative for what actually renders. This audit confirmed the two
agree on every screen — where an element is missing from the HTML it is also
missing from the PNG, which is why the previously-suspected "export
corruption" was resolved as a set of real absences and formally cut (§7.3).
**Do not recreate UI that is absent from the export**, and do not request a
re-export; the material in the repo is complete and audited.

This file follows the same rule the rest of this project already runs on: no
guessing. Every endpoint and field in Section 2 has been read directly out of
the live backend source with file:line citations — not paraphrased from an
earlier doc. Section 3 lists what does **not** exist yet — treat that list
as a hard boundary, not a suggestion.

**Revision — audited against the live repository (2026-08-24).** Every
endpoint path, request field, and response shape below has now been read
directly out of the running backend source (file:line citations inline),
not transcribed from an earlier doc. That audit corrected five defects
that would each have broken the build:

1. **All paths were missing the `/api/v1` prefix** — every call as
   previously written returned 404. Fixed throughout (`main.py:50-52`).
2. **`GET .../branches` returns a wrapped object, not a bare array**
   (`webhooks.py:176`).
3. **No CORS middleware exists anywhere in the backend** — a browser
   frontend on a different port is blocked on every request. Resolved via
   a Vite dev proxy (Section 8.4); no backend change.
4. **`severity` is an open string, not a 3-value union** — a live review
   returned six distinct values. Fixed in Sections 5 and 9.1.
5. **`question` IS forwarded for `review`** — the previous claim that Full
   Review drops it was false (`orchestrator_message.py:15-17,75`), and it
   had propagated into required UI copy and an acceptance test that would
   have failed. Corrected in Section 2.

Section 7's export audit was also rebuilt: several elements it described
as present ("Run Analysis", "System Normal") exist in **no** export file,
and its "export corruption" theory is contradicted by the exported PNGs.
The Stitch export — HTML **and** PNG together — is now the binding visual
source of truth (Section 7). The earlier ⚠️ over the `tool_calls` item
shape is **resolved**: verified at `review_session_repository.py:169-175`.

---

## 1. How to use this with OpenCode

1. Attach this file + the Stitch export (code, not just images) to the
   session.
2. Build in stages, mirroring how Phases 1–4 were built — don't one-shot the
   whole frontend:
   - **5a — Scaffold:** React + Vite + PWA project structure, routes/screens
     ported from the Stitch export, zero backend wiring, all data mocked
     in-memory.
   - **5b — Wire real endpoints:** replace mocks with the real calls in
     Section 2, one screen at a time. Anything in Section 3 stays mocked/
     stubbed per Section 4 — do not invent an endpoint to fill a gap.
   - **5c — PWA + polish:** manifest, service worker, offline fallback,
     responsive pass.
3. Tell OpenCode explicitly: PHASE_2.md, PHASE_3.md, and this file are ground
   truth for request/response shapes. If a screen needs data this file
   doesn't cover, stop and flag it — don't guess a field name or invent a
   route, the same standing rule already in effect for the backend phases.

### Converting Stitch's HTML/CSS export to React

Stitch outputs static HTML/CSS with Tailwind classes, not React — that's
expected, not a mismatch to fix. Treat the conversion as mostly mechanical:

- Tailwind classes carry over directly (`class` → `className`); don't
  re-derive colors/spacing from the screenshots — the classes in the
  exported HTML are the precise source, the PNGs are for confirming the
  result renders the same. See §9.3 for which token source wins where
  (the inline config, not `DESIGN.md`'s prose hexes).
- The export is one static HTML file per screen, not a routed app — split
  it into real React components matching the app's actual structure
  (`Sidebar`, `ChatThread`, `MessageComposer`, `RepoDropdown`,
  `BranchDropdown`, `EventFeed`, etc.), then compose each screen from those
  components. Don't keep five monolithic page components that each
  duplicate the sidebar/header markup. The sidebar differs between chat and
  Settings in the export — build **one** component from `chat.html`'s
  variant (§7.6).
- Everything in the export is static placeholder content (fake repo names,
  fake messages, dummy branch lists, a fabricated webhook URL, example
  findings). None of it is live data — replace all of it with real
  state/props per Section 2, and cut what §7.4 lists as fabricated. Don't
  leave any of Stitch's placeholder text or dummy data wired in.
- **Blank slots in the export are real absences, not damage.** Several
  `<button>`/`<li>` elements are present but empty, and several header slots
  are blank. These were audited against the PNGs and confirmed to render as
  nothing; §7.3 records each as cut. Do not "restore" them from guesswork.
- Nothing in the export is interactive — dropdowns, the composer, sidebar
  collapse, etc. are visual only. All real interactivity (state, handlers,
  controlled inputs) needs to be built fresh with React hooks; the export
  only supplies markup and styling to build that around.

---

## 2. Real endpoints — exact contracts (verified against live source)

**All routes are mounted under `/api/v1`** — `main.py:50-52` includes all
three routers with `prefix="/api/v1"`, and every `APIRouter()` is
constructed with no prefix of its own (`webhooks.py:23`, `review.py:70`,
`conversation.py:42`). These 8 are the *only* HTTP routes in the app.
Omitting the prefix yields a 404 on every call.

**No route declares a `response_model`** — every handler returns a plain
dict that FastAPI serializes verbatim. The shapes below are therefore
exact, with nothing filtered or coerced.

### `POST /api/v1/repos` — **final credential contract**
`webhooks.py:156` (to be extended; current source only has 2 fields — the
3 new fields are the minimal final-phase backend change, §3/§4)
```
Request:  {
  repo_url: str,            // required — https://github.com/owner/repo[.git]
  repo_id: str,             // required — "owner/repo", must match repo_url
  user_id: str,             // required — client-generated identity (decision 2)
  github_pat: str | null,   // required for private repos; optional for public
  webhook_secret: str | null // per-repo HMAC secret; server generates uuid4 hex if omitted
}
Response: {"status": "accepted", "repo_id": str, "credential_stored": bool}
```
400 if `repo_url`/`repo_id`/`user_id` missing or `repo_id` mismatches URL
(`webhooks.py:161-162` today; new validator added). 409 if `repo_id`
already owned by a different `user_id` (new `UNIQUE(repo_id)` on
`RepoCredential.owning_user_id`).

**Credential handling (final, not future):** `github_pat` and
`webhook_secret` are **write-only, encrypted server-side with
`Fernet(CREDENTIAL_ENCRYPTION_KEY)`, never returned, never logged, never
written to `.git/config` nor to browser storage** (§3 item 3/4, §4, leak
test §11). `POST` stores `repo_url_encrypted` too (currently not stored
at all — `models.py:12-22` has no `repo_url` column; re-clone after
eviction would otherwise be impossible). Subsequent `git clone/fetch`
and the GitHub MCP per-request `Authorization: Bearer <pat>` (see below)
use the vault row for `(repo_id)` — there is **no global PAT fallback**
in final phase (decision 3/8 item 3 — contradiction removed). Registration
(clone + graph build) still happens in a **background task**
(`webhooks.py:164`) — the response returns before it finishes. There is
**no status/progress endpoint** (Section 3) — see Section 4 for the
"registering…" UI state.

### `GET /api/v1/repos/{repo_id:path}/branches`
`webhooks.py:169`. `{repo_id}` contains a slash (`owner/repo`), so the
route uses `{repo_id:path}` — confirmed literally in source. A plain
`GET /api/v1/repos/acme/core-api/branches` therefore works unescaped.

```
Response: {"repo_id": str, "branches": [{name: str, sha: str, protected: bool}, ...]}
```
⚠️ **The response is an OBJECT wrapping the list, not a bare array**
(`webhooks.py:176`). `sha` is a top-level key on each item, not
`commit.sha` (`branch_resolution.py:59-60`).

Status codes: `404` unregistered repo (`webhooks.py:172-173`);
**`500`** if the GitHub MCP tool returns a non-JSON or unexpected payload
(e.g. a rate-limit error body) — `BranchNotFoundError` is raised at
`branch_resolution.py:44-50` and is **not caught** in this route (only
`resolve_branch_to_commit` is guarded, `review.py:114-115`). Handle 500
here as a real possibility, not a can't-happen.

This is the **only** valid source for the branch dropdown. Do not populate
it from a locally-cached list of "branches already reviewed" — this
endpoint proxies live GitHub branches. ⚠️ Pagination on the underlying
GitHub tool is explicitly unverified (`PHASE_2.md:401`) — a repo with many
branches may return a partial list. See Section 6 for the required
manual-entry fallback.

### `POST /api/v1/conversations`
`conversation.py:59`
```
Request:  {repo_id: str, user_id: str}               // both required
Response: {"conversation_id": int, "repo_id": str, "user_id": str, "status": str}
```
⚠️ **Exactly 4 keys** (`conversation.py:64-69`) — there is no `id` key
(it is renamed to `conversation_id`) and **no timestamps**, despite what
an earlier revision of this doc claimed. `status` is `"active"` on create.

Call this once, when the user hits "New conversation." A conversation is
bound to one `repo_id` for its lifetime.

### `POST /api/v1/conversations/{conversation_id}/message`
`conversation.py:72`. Note the path param is named `conversation_id`.
```
Request:  {user_id: str, repo_id: str, content: str}   // all required
Response:
  {
    "conversation_id": int,
    "user_message": str,                 // echoed input
    "context": null | {
        "conversation_id": int,
        "results": [{message_id: int, role: str, snippet: str,
                     created_at: str|null, score: float}],
        "error": str | null,
        "latency_ms": int
    },
    "tool_calls": [ ... ]                // see below
  }
```
Exactly 4 top-level keys (`run_conversation_turn.py:101-106`). `context`
is `null` when recall failed (`:142`). `tool_calls` is **empty** unless
recall returned results (`:87`), and holds **at most one** entry, always
`tool_name="search_messages"` (`:88-99`).

⚠️ **These `tool_calls` are a DIFFERENT shape from the review
`tool_calls`** in `GET /api/v1/reviews/{session_id}`. This one comes from
the domain `ToolCall` dataclass via `tc.__dict__`
(`run_conversation_turn.py:105`, `conversation_entity.py:26-34`) and has
`message_id`, `tool_name`, `tool_input`, `tool_output`,
`tool_latency_ms`, `tool_status`, `id`. Do not share a TypeScript type
between the two.

**⚠️ This does NOT return an assistant answer.** It persists the user's
message and runs a recall/evidence lookup only. There is no
`assistant_reply` or `answer` key (`conversation.py:9-13`). 404 if the
conversation doesn't exist. Do not render its response as a chat reply.

### `POST /api/v1/review` — this is what actually answers the user
`review.py:98`. Request model: `models.py:11-19` (plain `BaseModel`, no
validators — cross-field rules are enforced in the route).
```
Request:
  repo_id: str                       # required
  graph_commit_hash: str | None      ─┐ exactly ONE of these two required
  branch: str | None                  ┘ (400 if both or neither)
  request_type: str                  # one of the 7 keys below; 400 if unknown
  diff_content: str | None           # optional — see note below
  question: str | None               # the user's message content
  conversation_id: int | None
  user_id: str | None                # REQUIRED (400) if conversation_id is set

Response:
  {
    "review_session_id": int,
    "result": <JSON STRING of the aggregated AgentOutput>,
    "timeline": {<agent>: [{"kind": "llm"|"tool", "name": str, "duration_ms": int}, ...]},
    "timeline_text": <plain-text rendering of the timeline>
  }
```
⚠️ **`result` is a JSON string here** (`review.py:228` —
`json.dumps(...)`) — you must `JSON.parse()` it. On
`GET /api/v1/reviews/{session_id}` the same field name is an **already-
parsed dict** (`review.py:304`). The asymmetry is real; do not share one
type between them.

Status codes: `400` unknown `request_type` (`review.py:103`) or
both/neither `branch`/`graph_commit_hash` (`review.py:237-240`);
`404` unregistered repo (`review.py:124`) or unknown branch
(`review.py:115`); `425` graph not ready — a background rebuild has been
kicked off (`review.py:134-138`, returned as a `JSONResponse` rather than
raised so the BackgroundTask survives); `500` `{"detail": "Review failed"}`
(`review.py:201`). See Section 4 for the 425 retry pattern.

**On `diff_content` — verified optional, and unreachable from this UI.**
The backend does not need a client-supplied diff. `DiffInjectionMiddleware`
takes `diff_content or ""` and every repair path early-returns when it's
empty (`middleware.py`, covered by
`test_middleware.py::test_no_op_without_diff`), and the orchestrator emits
an explicit alternate instruction in that case
(`orchestrator_message.py:88-90`). Specialists derive change context
themselves from CRG (`detect_changes_tool`, `get_impact_radius_tool`,
`get_affected_flows_tool`, `get_review_context_tool` —
`tool_lists.py:101-134`) and from GitHub's `pull_request_read`, which the
specialist prompts document as "the actual diff" (`security.md:5`,
`regression.md:5`, `performance.md:5`, `compliance.md:7`). Empirically
confirmed: review session 168 ran `compliance_question` with
`diff_content` omitted and completed with 9 findings and 8/8 successful
tool calls.

Because the Stitch export contains **no** diff or snippet input (Section
7), `diff_content` keeps its place in the request type but has **no UI
path in Phase 5**. Keep the field optional in TypeScript and always omit
it. One honest consequence to be aware of: with no diff supplied, the
aggregator's diff cross-check guard (`aggregator.md:6`, which drops
findings claiming changes absent from the diff) is inert, so a Phase 5
review is scoped to the branch's committed state as the CRG graph
understands it. Do not add a diff textarea to "fix" this — that is a
product decision, not an implementation gap.

**Every chat turn is therefore two calls, in order:**
1. `POST /api/v1/conversations/{conversation_id}/message` — persist + get
   evidence (optional to show in the UI, but do not treat its response as
   the reply).
2. `POST /api/v1/review` with the same `conversation_id`/`user_id`,
   `question` set to the message content, and the currently-selected
   `repo_id`/`branch`/`request_type` — **this response is the assistant's
   chat bubble.** It is the *only* authoritative source of the final
   answer — see the polling endpoints below for what changed and what
   didn't.

### `GET /api/v1/reviews/running` and `GET /api/v1/reviews/{session_id}`

These two endpoints exist to show progress *during* a still-running
`POST /api/v1/review`, without making `/review` asynchronous — **`POST
/api/v1/review` is still fully synchronous and still the sole source of
the final answer.** These are a *supplementary, poll-only* progress
channel, nothing more.

Route order is load-bearing: `/reviews/running` (`review.py:272`) is
declared **before** `/reviews/{session_id}` (`review.py:290`) so
first-match-wins resolves `running` as a literal, not as a session id.
Asserted by `test_review_status_endpoints.py:28-34`.

```
GET /api/v1/reviews/running?conversation_id={int}&user_id={str}
Both params REQUIRED (no repo_id fallback — deliberately removed).

Found:    {"review_session_id": int, "status": str, "created_at": str|null}
No match: {"review_session_id": null, "status": null}      // NOT an error
```
⚠️ **The no-match branch omits `created_at` entirely** — it returns two
keys, not three with a null (`review.py:282` vs `:283-287`). Type it as
optional, not merely nullable.

```
GET /api/v1/reviews/{session_id}?user_id={str}
user_id REQUIRED.
Response:
  {
    "review_session_id": int,
    "status": "running" | "completed" | "failed" | null,
    "repo_id": str,
    "request_type": str,
    "created_at": str | null,
    "completed_at": str | null,
    "duration_ms": int | null,
    "error": str | null,
    "result": object | null,       // PARSED dict once status == "completed", else null
    "tool_calls": [ ... ]          // exactly 5 keys per item — see below
  }
404 if session_id doesn't exist OR user_id doesn't match the session's
stored user_id — same 404 either way, so a mismatch never reveals that a
session exists (deliberate, review.py:297-299).
```
`status` can also be **`null`** for pre-migration legacy rows — the column
is `str | None` with no CHECK constraint (`models.py:45`). Values written:
`"running"` (`review_session_repository.py:45`), `"completed"` (`:122`,
the path the happy case actually uses), `"failed"` (`:95`).

**`tool_calls` item shape — VERIFIED** (`review_session_repository.py:169-175`),
exactly 5 keys:
```
{agent_name: str, tool_name: str, tool_latency_ms: int|null,
 tool_status: "success"|"error"|null, created_at: str|null}
```
There is **no `id`, no `review_session_id`, no `tool_input`, no
`tool_output`** — the underlying `ReviewToolCall` table
(`models.py:138-156`) does carry `id`/`review_session_id`, but
`get_tool_calls` does not project them, and input/output are omitted from
the table by deliberate privacy design. Do not add fields.

⚠️ **The query has no `ORDER BY`** (`review_session_repository.py:165-167`)
— rows come back in insertion/rowid order, which is *usually* chronological
but is not a contract. Do not build loop-detection or sequencing logic that
depends on ordering; sort client-side on `created_at` if order matters.

**Both endpoints use the same self-asserted `user_id` model as everywhere
else in this API (Section 3) — not real authentication.**

**Hard rule, extending the two-call rule above: never use `GET
/api/v1/reviews/{session_id}`'s `result` field as the source of the final
answer, even after it shows `status: "completed"`.** These endpoints exist
purely to show progress *while waiting* for `POST /api/v1/review` to
return; using them as an alternate path to "the answer" introduces a race
between two independent requests that doesn't need to exist. See Section 4
for the polling flow.

### Request-type values (`routing_policy.py:13-21` — all 7, use exactly these keys)
`review`, `security_question`, `compliance_question`, `performance_question`,
`impact_question`, `explain_question`, `any_question`

Subagents dispatched per type:

| `request_type` | Specialists dispatched |
|---|---|
| `review` | compliance, security, performance, regression |
| `any_question` | compliance, security, performance, regression |
| `security_question` | security |
| `compliance_question` | compliance |
| `performance_question` | performance |
| `impact_question` | regression |
| `explain_question` | **none** — orchestrator answers directly |

⚠️ `explain_question` routes to an empty agent list
(`routing_policy.py:19`), so **no specialist tool calls are ever persisted
for it** — the live `tool_calls` feed stays legitimately empty for that
type for the whole run. Section 6's "don't show stuck" rule must account
for this: for `explain_question`, an empty feed is the expected state, not
a gap.

**Composer dropdown labels do not slugify to these keys — map explicitly.**
The Stitch export supplies only one dropdown label ("Any Question",
`chat.html:274`); the rest are specified here because no export provides
them:

| Composer dropdown label | `request_type` value |
|---|---|
| Any Question *(default)* | `any_question` |
| Full Review | `review` |
| Security Audit | `security_question` |
| Compliance Check | `compliance_question` |
| Performance | `performance_question` |
| Impact Analysis | `impact_question` |
| Explain Code | `explain_question` |

A naive slugify ("Security Audit" → `security_audit`) is a `400`. Use this
table verbatim; don't derive the key from the label text. The composer
dropdown is the **only** request-type selector in Phase 5 — the sidebar
shortcuts were cut (Section 7).

### How a Jira ticket key actually reaches a specialist

There is no structured "ticket key" or "project key" field anywhere in
`ReviewRequest`. The **only** way to reference a specific ticket (e.g.
`CLIP-3`) is to type it into the free-text message — the orchestrator
forwards `question` verbatim into the specialist's task description as a
"Question from the user: …" section (`orchestrator.md:4`), and Compliance
is the specialist holding `jira_get_issue` (`tool_lists.py:98`), so that's
what resolves the key.

⚠️ **Corrected:** an earlier revision of this doc claimed `review` and
`explain_question` do not forward `question`, and drew the conclusion that
"Full Review mode won't reliably carry a ticket reference to Compliance."
**That is false.** The actual set (`orchestrator_message.py:15-17`) is:

```python
_QUESTION_CARRYING_TYPES = frozenset(
    {"review", "compliance_question", "security_question",
     "performance_question", "impact_question"}
)
```

`review` **is** included, gated at `orchestrator_message.py:75`, and the
source comment at `:12-13` states the intent explicitly: "`review` (full
pipeline) forwards it too so users can give the orchestrator both the diff
and a linked Jira ticket key in one prompt." `any_question` also always
includes the question via its own branch (`:50-51`).

**Only `explain_question` drops `question`.** Practical consequence for
the UI: a ticket key typed into the message works in every mode except
Explain Code. Do **not** add composer copy warning that Full Review won't
forward it — that copy would be factually wrong.

This mechanism doesn't change if per-user Atlassian OAuth gets built
(Section 3) — the ticket key still travels as free text in `question`.

---

## 3. Does NOT exist yet — do not call, do not invent

- **No `GET /api/v1/repos` of ANY kind.** There is no endpoint to list a
  user's GitHub repos *and no endpoint to list already-registered repos
  either*. `POST /api/v1/repos` (register) and
  `GET /api/v1/repos/{repo_id:path}/branches` (branches for one known repo)
  are the only repo routes that exist — verified by enumerating every
  `@router` decorator in the package. `RepoWorkspace` (`models.py:12-22`)
  and `GraphSnapshot` (`models.py:25-32`) are never exposed over HTTP.
  Consequence: **both** the onboarding repo list and Settings' "Connected
  Repositories" list must be rendered from a client-side cache of
  successful `POST /api/v1/repos` calls (Section 4). This is a stub, not a
  wiring task.
- **No CORS middleware anywhere in the backend.** Verified: zero matches
  for `CORSMiddleware`/`add_middleware`/`allow_origins` across the entire
  `backend/` tree; `main.py` (52 lines) only calls `include_router` three
  times. A browser frontend served from a different origin/port is blocked
  on **every** request, including preflight `OPTIONS`. This is resolved
  frontend-side with a Vite dev proxy — see Section 8.4. Do not add
  `CORSMiddleware` to `main.py` as part of Phase 5; that is a backend
  change outside this phase's scope and requires explicit authorization per
  `AGENTS.md`.
- **No `GET /api/v1/conversations`** (no list-conversations-for-a-user endpoint).
- **No readiness/status-poll endpoint** for repo registration or branch
  builds — and re-polling `POST /api/v1/review` isn't free. PHASE_2.md's own
  authors flag this exactly (`PHASE_2.md:402`): "the only way to distinguish
  'graph still building' (425) from 'done' (200) is to re-submit the full
  review payload, which re-runs the pre-flight and **could re-queue work**."
  A per-branch lock (`EnsureBranchWorktreeService` releases it in a
  `finally`) likely prevents two builds literally racing, but repeated
  polling still re-triggers pre-flight + dispatch attempts needlessly.
  PHASE_2.md sketches the fix:
  `GET /api/v1/repos/{repo_id}/branches/{branch}/readiness`
  → `{"ready": true, "commit": ...}` or `{"ready": false}`. **This endpoint
  does not exist yet** — if/when it's built, match this shape rather than
  inventing a different one; until then, poll `POST /api/v1/review` itself
  and accept the inefficiency (see Section 4).
- **No GitHub OAuth / no auth or tenant-identity system of any kind.**
  `user_id` is just a free string the client sends — there is no session,
  login, `User` table, or request authentication middleware anywhere in the
  backend (documented in-source at `review.py:20-26`, `conversation.py:3-4`).
  This is a hard architectural fact, not a missing detail: a frontend
  "Sign in with GitHub" screen can be built to the Stitch design, but it
  **cannot actually authenticate anyone** until backend AuthN/AuthZ exists
  — it can only collect/generate the free-form `user_id` string the API
  already expects (see Section 4). Don't let the screen's polish imply a
  security boundary that isn't there.
- **No per-user Jira/Atlassian connection today — see the dedicated
  subsection below** ("Atlassian OAuth — target vs. current state").
- **No webhook-registration endpoint callable from the app.** The only
  webhook route is `POST /api/v1/webhook` (`webhooks.py:28`), which is
  GitHub's *inbound* delivery target and requires an HMAC
  `X-Hub-Signature-256` header. Webhooks are wired manually today (GitHub
  repo settings pointing at a public URL). There is no endpoint that
  generates a webhook URL or token — see Section 7's note on the fabricated
  onboarding webhook URL.
- **Still no push-based streaming (SSE/WebSocket) — but there is a
  poll-based progress channel.** `POST /api/v1/review` remains fully
  synchronous; a real async `/reviews` design (background queue,
  lease/retry, cancellation) was considered and explicitly **not built** —
  the team chose the smaller `GET /api/v1/reviews/running` + `GET
  /api/v1/reviews/{session_id}` polling endpoints instead (Section 2). What
  this does and doesn't give you:
  - Does: near-real-time visibility into which tools are being called,
    polled during the wait.
  - Does not: true push/live streaming, cancellation, or any change to
    `POST /api/v1/review` itself still blocking for the full duration.
  - Does not: capture LLM "thinking" time — only tool calls are persisted
    (Section 5/6) — so gaps in the polled list are expected and normal.
  - Does not: apply at all to `explain_question`, which dispatches no
    specialists (`routing_policy.py:19`) and therefore produces no
    specialist tool calls for the entire run.
  - Persistence is explicitly **best-effort** — the write "never raises,"
    meaning a failed write is silently swallowed server-side. Don't treat
    an empty poll response as evidence nothing is happening.

### GitHub & Jira credentials — final architecture (OAuth removed)

**Decision 1 — no OAuth of any kind.** GitHub OAuth and Atlassian OAuth
are **deleted** from scope: no `/auth/*` route, no redirect, no token
exchange, no "Continue with GitHub (OAuth)" or "Connect Atlassian
(OAuth 2.0)" copy. This is final — there is no later phase that will add
it.

**GitHub — per-user PAT, wired into both `git` and the MCP (item 1).**
Today `github_pat` is a single global env (`config.py:62`) sent once as
`Authorization: Bearer` in `mcp_client_factory.py:49`, and `git clone/fetch`
in `git_repo_source.py:48-92` uses bare `subprocess` with no credential —
private repos fail in Docker. Final: a vault row
`RepoCredential(repo_id PK, owning_user_id, repo_url_encrypted,
github_pat_encrypted, webhook_secret_encrypted)` holds the PAT **encrypted
with `Fernet(CREDENTIAL_ENCRYPTION_KEY)`**, written on `POST /api/v1/repos`.
The MCP path builds per-request headers via
`build_github_headers_for_repo(repo_id)` → `{"Authorization": "Bearer <pat>"}`;
`mcp_client_factory.build_mcp_client(github_pat_override=…)` creates a
per-review ephemeral client for `branch_resolution.py:33` and agent tools.
The `git` path gains `pat: str | None` on `GitRepoSource.clone/sync/…`
and injects it via `http.extraHeader` / credential helper — **never via
`https://token@` URL that leaks into `.git/config`**.

**Jira — per-user Basic via `mcp-atlassian` UserTokenMiddleware (item 5 is
blocking).** Verified in the installed package `mcp_atlassian@0.23.0`:
`servers/main.py:668-728` parses `Authorization: Basic base64(email:token)`
→ `servers/main.py:726-728` stores `user_atlassian_email/api_token` with
`auth_type="basic"` → `servers/dependencies.py:884-914` creates a
**user-specific `JiraFetcher`** per request, validated by
`get_current_user_account_id()`. The only still-unverified tail is whether
`dependencies.py:697` `url: base_config.url` inheritance requires a dummy
global `JIRA_URL` to remain; **spike task before wiring must probe a live
header round-trip** and, if it hits the placeholder, apply the one-line
`user_config.url = user_jira_url` override. Final frontend sends per-review
`{"Authorization": "Basic <b64>"}` built from vault row
`(user_id → jira_url, jira_email, jira_api_token_encrypted)`; no global
Jira token is used for user work. `ALLOW_GLOBAL_CRED_FALLBACK` is set
`false` — the global fallback that today's `run_atlassian_server.sh:36`
relies on is deleted as a contradiction (item 3).

**Webhook — identity resolved, manual registration (item 2).**
`handle_webhook` today reads only `payload["repository"]["full_name"]`
(`webhooks.py:39`) and verifies with a single global `settings.github_webhook_secret`
(`webhooks.py:33`). `RepoWorkspace:12-22` has no `user_id`/`webhook_secret`/`repo_url`
and `UniqueConstraint(repo_id,branch)` lets a second `user_id` silently
hijack the first. Final: the same `RepoCredential` row owns the webhook
secret per `repo_id`; the handler does `SELECT * FROM repocredential WHERE
repo_id=:repo_id` **after** parsing `repo_id`, then
`hmac.compare_digest("sha256="+hmac.new(secret, raw_body, sha256).hexdigest(),
header)` against that row's secret — **no global fallback** (item 3).
Two `user_id`s on one `repo_id` now returns `409`. Registration remains
**manual**: GitHub → Settings → Webhooks → Payload URL
`= <origin>/api/v1/webhook`, Secret = the value entered on `POST
/api/v1/repos`, Events = Push only. No registration endpoint is invented:
GitHub remote MCP is `X-MCP-Readonly:true` across 6 toolsets
(`repos,issues,pull_requests,code_security,dependabot,actions`) and no
`webhooks`/`admin` toolset exists (`tool_lists.py:36-63` — 12 read-only
tools), so automatic registration is impossible.
  (Section 4), not as if real OAuth is already wired.

---

## 4. How to handle each gap in this build (stub strategy)

- **Repo lists (onboarding step 1 AND Settings "Connected Repositories") —
  client-side cache only.** There is no `GET /api/v1/repos` of any kind
  (Section 3), so neither list has a server-side source. Maintain a local
  (IndexedDB) record of every `repo_id` successfully registered via
  `POST /api/v1/repos` and render both lists from it. Label it plainly as a
  local cache — it won't survive a new device/browser. Do **not** invent a
  repo-listing endpoint URL, and do not silently present the cache as if it
  were server state.
- **Repo index state (`Indexed` / `Indexing…`) — not derivable; collapse
  it.** `onboarding.html:215-240` shows three states, but `GraphSnapshot.status`
  (`models.py:29`) — the only place "ready" actually lives — is exposed by no
  endpoint. Render a **binary** registered / not-registered state instead,
  using the indeterminate "Indexing…" treatment (already in the export at
  `onboarding.html:231`) for "registration submitted, completion unknown."
  Never show a state that implies the backend confirmed indexing finished.
  Real tri-state requires the readiness endpoint from Section 3 as new
  backend work.
- **Repo-registration / branch-build progress:** since there's no status
  endpoint, drive the "preparing…" UI state client-side: show a progress
  state after `POST /api/v1/repos` or a 425, and clear it on the next
  successful `POST /api/v1/review` (or a manual retry button) rather than
  tight-polling a nonexistent route.
- **Conversation list sidebar:** persist conversation metadata client-side
  (IndexedDB, since this is a PWA) keyed by the `conversation_id` returned
  from `POST /api/v1/conversations`, until a real list endpoint exists.
  Label it clearly as a local cache, not a synced list.
- **Sign-up / GitHub OAuth — mock identity baseline:** build the screen per
  the Stitch design, but wire it to a placeholder that collects or generates
  a `user_id` string client-side and sends that on every request — not a
  real OAuth token exchange, since there's nothing on the backend to
  exchange it with (Section 3). Do not build a fake OAuth redirect that goes
  nowhere.
- **Jira/Atlassian OAuth UI — build the full shell, stub the wiring:**
  build the "Connect Atlassian" / connected-state / Disconnect / Configure
  UI exactly per the Stitch design. Wire "Connect Atlassian" to a
  clearly-labeled placeholder — no real redirect, since
  `/auth/atlassian/authorize` doesn't exist. Don't build a "connected" state
  that persists across reloads (there's no token storage to persist it in);
  a page refresh should show "not connected" again. "Configure" has no
  defined behavior anywhere — treat it as a no-op placeholder.
- **`diff_content` — no UI path, keep the field.** Verified optional
  (Section 2): the backend derives change context from CRG and GitHub, and a
  review completes successfully with the field omitted. The Stitch export
  contains no diff or snippet input, so per Section 7's export-fidelity rule
  nothing is built for it. Keep it optional in the request type and always
  omit it.
- **"Agent working" live feed — genuinely near-live, with real gaps:**
  while `POST /api/v1/review` is in flight, run a separate polling loop
  (`GET /api/v1/reviews/running` → then `GET /api/v1/reviews/{session_id}`)
  to grow the feed with real `tool_calls` entries as they're persisted. This
  is real progress, not a post-hoc animation — but it has real gaps and the
  UI must not pretend otherwise:
  - There will be silent stretches with no new rows during LLM "thinking"
    time (tool calls only). Don't show "stuck" for this; a generic "still
    working" indicator between tool-call entries is honest.
  - For `request_type: "explain_question"` there will be **no specialist
    rows at all, ever** — no subagents are dispatched
    (`routing_policy.py:19`). Treat a permanently empty feed as correct for
    that mode rather than as a stall.
  - Persistence is best-effort — a missing entry doesn't mean a tool wasn't
    called. Don't build logic that depends on the list being complete.
  - Rows are **not guaranteed ordered** (no `ORDER BY`,
    `review_session_repository.py:165-167`). Sort client-side on
    `created_at` if you display sequence.
  - When `POST /api/v1/review` itself returns, that response — not anything
    from the polling loop — renders as the final answer (Section 2's hard
    rule). Stop polling once it resolves.
  - Poll interval is a UI choice, not a backend-mandated value; pick
    something reasonable (a couple of seconds) and tune against the real
    backend.

---

## 5. Event/timeline shape (for the "agent working" feed)

Each `timeline` entry: `{"kind": "llm" | "tool", "name": str, "duration_ms": int}`,
grouped by agent key in the `timeline` dict (e.g. `compliance`, `security`,
`performance`, `regression`, orchestrator-level entries). There is no
separate "subagent started" event — an agent's presence is just its key
appearing in the `timeline` dict with entries under it.

**⚠️ `timeline` carries call names and durations only — never finding
content, and `name` is a real MCP tool name, not decorative text.** There is
no "SAST scanner" or any other invented tool anywhere in this backend; a
`tool` entry's `name` is whatever the actual MCP tool is called
(`pull_request_read`, `jira_get_issue`, `confluence_search`, `list_commits`,
a CRG graph-query tool, etc.). Render `timeline[agent][i].name` verbatim —
never hardcode an example tool label from the Stitch export.

**Two separate data sources now exist for agent activity — do not conflate
them:**

| | `timeline` (in `POST /api/v1/review`'s response) | `tool_calls` (from `GET /api/v1/reviews/{session_id}`, Section 2) |
|---|---|---|
| Contains | `llm` **and** `tool` entries | `tool` entries only |
| Grouped by agent? | Yes, keyed by agent in the response | No — flat list, each row has its own `agent_name` field |
| Available when | Only after the full review finishes | Live, polled while the review is still running |
| Completeness | Complete (part of the final response) | Best-effort — a write "never raises," so gaps can exist silently |
| Ordering | Per-agent, in capture order | **Not guaranteed** — no `ORDER BY` (`review_session_repository.py:165-167`); sort client-side on `created_at` |
| `explain_question` | orchestrator entries only | **always empty** — no subagents dispatched (`routing_policy.py:19`) |

Use `tool_calls` for the live "working" feed (Section 4), and `timeline`
for the complete, authoritative record once the response lands — they're
not interchangeable, and `tool_calls` should not be treated as a subset
guaranteed to match `timeline`'s tool entries exactly.

**⚠️ Individual findings have no per-agent attribution, and are never
available before the full response lands.** `AgentFinding`
(`agent_finding.py:16-23`) = `{severity: str, confidence: float, title,
description, evidence: list[str], recommendation}` — no field says which
specialist produced it. Worse: `POST /api/v1/review`'s `result` field is
only the single **aggregated** `AgentOutput` (one `agent_name`, one combined
`findings` list, plus `parse_status`) — the per-specialist breakdown
(`ReviewResult.per_agent`) is written to the DB as `AgentExecution` rows
(`models.py:59-68`) but is **never returned by any endpoint**. So a UI card
showing "SecurityAgent found: hardcoded secret…" — a specific finding
visually attributed to one named specialist — cannot be built as the export
draws it; there is no data path supplying that attribution. **This is
unchanged by the polling endpoints** — they add tool-call visibility, not
finding attribution. See Section 7 for how to resolve the display problem.

### 5.1 `severity` is an OPEN string — not a three-value union

⚠️ **Corrected.** An earlier revision typed this as
`"info" | "warning" | "critical"`. Nothing in the system enforces that:

- `AgentFinding.severity: str` — plain dataclass, no `Literal`, no
  validator (`agent_finding.py:18`).
- `FindingItem.severity: str = Field(description='"info" | "warning" | "critical"')`
  — the enum exists **only inside a description string**
  (`report_schema.py:17`), so any value passes validation. The one validator
  on that model touches `confidence`/`title`, never `severity`
  (`report_schema.py:24-31`).
- Values are **lowercased** and default to `"info"` when absent
  (`orchestrator_parsing.py:122`).
- No DB constraint — findings are stored as JSON inside
  `AgentExecution.result` (`models.py:67`).
- Only the aggregator prompt enumerates the triple (`aggregator.md:9`);
  specialist prompts don't (`security.md:20`, `performance.md:20`,
  `regression.md:19`, `compliance.md:21`).
- A repo test fixture already uses `"medium"`
  (`test_review_session_repository.py:45`).

**Empirically, a single live review (session 170) returned six distinct
severities:** `info` ×12, `medium` ×5, `critical` ×5, `warning` ×4,
`high` ×3, `low` ×2. A three-branch renderer would have mis-handled 10 of
those 31 findings.

**Required handling:**
1. Type it `string`, not a union.
2. Lowercase-normalize on receipt (the backend usually does, but the strict
   parse path passes values through untouched — `orchestrator_parsing.py:39`).
3. Sort/group by this explicit order, highest first:
   `critical` → `high` → `warning` → `medium` → `low` → `info`.
4. Any value not in that list renders with the `info` treatment and its raw
   text as the label. Never drop a finding because its severity is unknown.

`confidence` **is** constrained `0.0–1.0` (`report_schema.py:18`) and is
safe to treat as a bounded float.

### 5.2 `parse_status` — present on the aggregated result, and worth surfacing

`AgentOutput` carries a third field the earlier revision omitted:
`parse_status` (`agent_finding.py:30`), serialized by
`dataclasses.asdict` into `result`. Values: `"ok"`, `"parse_failed"`,
`"empty_output"`, `"fallback_from_specialists"`. Session 170 returned
`"fallback_from_specialists"`.

Anything other than `"ok"` means the aggregator did not produce clean
structured output and the result was salvaged (the two synthetic
parse-failure findings are emitted at `severity: "warning"` —
`orchestrator_parsing.py:183,255`). Surface this as a quiet caveat on the
answer rather than hiding it; it is real signal about answer quality.

### 5.3 Real `agent_name` values

The export's labels ("Orchestrator", "SecurityAgent", "PerfAgent") are
**not** the values the API returns. Actual `agent_name` strings:

| Source | Values |
|---|---|
| `tool_calls[].agent_name` | `compliance`, `security`, `performance`, `regression`, `fix_suggestion`, `context_agent` |
| `timeline` keys | the same, plus `aggregator` |

Session 170's `tool_calls` contained exactly `context_agent`,
`performance`, `compliance`, `security`, `regression`. Map these to display
labels and colors via Section 8.5's table — never render the export's
hardcoded label text, and never assume an agent name matches a label.

---

## 6. Model fidelity risks — logged incidents, not generic caveats

These are two real, dated incidents from this project's own test sessions
(`OPENCODE.md`), not hypothetical LLM caveats. Both are scoped to
`manage_memory`/`search_memory` — the memory-write tools used by Phase 4's
Context Agent — not proven to generalize to the GitHub/Atlassian/CRG tool
calls the review specialists use, though the same defensive rules are cheap
enough to apply everywhere.

**Phantom tool claims (P1, sessions 118–121) — historical, already fixed.**
The active `REVIEW_MODEL` at the time (`nemotron-3-ultra-550b-a55b`)
rendered `manage_memory`/`search_memory` calls as text inside its
`thinking` output instead of emitting real structured tool calls, then
reported success anyway — memory silently no-op'd while the answer said
"stored." Fixed 2026-08-19 with a dedicated parser middleware for that
model's nonstandard tool-call format. `REVIEW_MODEL` is a swappable config
setting, so treat this as a real, if currently patched, failure class:
**never treat the final answer's own text as proof an action happened** —
the only trustworthy signal is a real entry in the returned `timeline`
(Section 5). This is already the rule for findings; extend it to any
claimed action.

**Tool execution loops (P4, logged 2026-08-19) — current, unresolved,
HIGH severity.** The same model re-issues the **identical** content-less
`manage_memory` call 4–5× after receiving a "content is required" error,
never adding the content, then gives up and echoes the error as its final
answer — session 129 burned 997s (16.6 min) this way, session 130 burned
241s. Logged explicitly as a model-capability limit, not a harness bug:
"no middleware can force the model to comply."

**What this means for the UI:** post-Phase-4, the frontend now has
**partial** real-time visibility via `GET /api/v1/reviews/{session_id}`'s
`tool_calls` polling (Section 2/4) — this changes what's possible here,
though not everything:
- **Near-real-time loop detection is now genuinely possible** — poll and
  watch for the same `tool_name`, same `agent_name`, repeated back-to-back
  with `tool_status` alternating or repeating. That's a real, live signal
  a loop like P4 is happening, not just a post-hoc one. Surface it as a
  visible note once a threshold is crossed (e.g. 3+ identical consecutive
  calls) — but two caveats: persistence is best-effort, so treat this as a
  helpful signal rather than a guaranteed detector; and the polled rows are
  **not guaranteed to be in chronological order** (no `ORDER BY`,
  `review_session_repository.py:165-167`), so sort on `created_at` before
  evaluating "consecutive" or the detector will produce false positives.
- **LLM "thinking" time is still invisible** — only tool calls are
  persisted (Section 5), so a model reasoning at length between tool calls
  produces no polling signal at all. Don't show a fixed/fake ETA regardless.
  Past some threshold (a normal run is 30–90s), a generic "still working,
  this can take several minutes" state remains correct for the gaps.
  Calibration note from real runs: a single-specialist
  `compliance_question` took **186s** and a 4-specialist `review` took
  **455s** — so the 30–90s figure is optimistic for anything beyond one
  specialist. Do not treat multi-minute waits as abnormal.
- **`explain_question` produces no tool-call rows at all** — it dispatches
  no subagents (`routing_policy.py:19`). An empty feed for that mode is
  correct, not a stall; the loop-detection and "silent stretch" logic must
  not flag it.
- Don't add an aggressive client-side timeout — killing the request
  client-side doesn't stop the server-side work already in flight, and a
  legitimate loop can legitimately run 15+ minutes. If a hard timeout is
  added for UX reasons, make it generous and clearly label it as "no
  response yet," not "failed."
- Once the full response lands, the returned `timeline` remains the
  complete, authoritative record — cross-check it against whatever was
  polled if useful, but `timeline` is the one guaranteed-complete source
  (Section 5's comparison table).

**Defensive rendering, tied to gaps already in this doc:**
- Branch dropdown: since `list_branches` pagination is unverified (Section
  2), add a manual branch-entry fallback (plain text input) alongside the
  dropdown so a large repo's truncated list doesn't hard-block a review.
- Tool-status badges / the "agent working" feed: source only from
  `tool_calls` (live, while running) and `timeline` (complete, once
  finished) — per Section 5's comparison table — never parse or infer
  status from the free-text final answer.

---

## 7. Stitch Export Audit — re-audited against HTML **and** PNG

**Binding rule for this phase: the Stitch export is the visual source of
truth, and the exported PNG is treated as the authoritative rendering of
each HTML file.** Do not recreate UI elements that are absent from the
export. The only exceptions are elements explicitly required by a backend
capability that would otherwise be unreachable — and each such exception is
named below.

This section was rebuilt after a full re-audit: every claim was checked
against all five HTML files by grep and against all five PNGs by direct
inspection. Three earlier claims were factually wrong and have been removed.

### 7.1 Screen inventory (5 HTML + 5 PNG + DESIGN.md)

| File | Screen | Sidebar? |
|---|---|---|
| `sign_in_reviewmind/sign_in.html` | Sign-in | no |
| `onboarding_reviewmind/onboarding.html` | Onboarding "Environment Setup" | no (own header) |
| `chat_reviewmind/chat.html` | Main chat / review | yes (`<aside>`) |
| `settings_reviewmind/settings.html` | Settings — Jira **not** connected | yes (`<nav>`) |
| `settings_connected_reviewmind/settings_connected.html` | Settings — Jira **connected** | yes (`<nav>`) |

The two Settings files are **two states of one component**, not two
screens. `reviewmind/DESIGN.md` carries the design tokens (see §9.3 for
which source wins where).

### 7.2 Real — wire per Section 2

"Continue with GitHub" (mock identity, §4), repo/branch dropdowns
(`chat.html:117-126`), the composer's request-type dropdown
(`chat.html:272-276`), the composer send button (`chat.html:288-290`),
Settings' "Add Repo" (`settings.html:211`), onboarding's per-repo "Connect"
button (`onboarding.html:239`) → all map to real endpoints or to the
Section 4 stub strategy.

⚠️ Onboarding's **repo list itself** (`onboarding.html:211-240`) was
previously classified here as "Real." **It is not** — there is no
`GET /api/v1/repos` of any kind (Section 3). Both it and Settings'
"Connected Repositories" list are Section 4 client-side-cache stubs. The
"Search repositories…" input filters that local cache only.

### 7.3 CUT — decided, not pending

These are settled decisions. Do not build them, and do not re-open them on
the grounds that an export might be incomplete.

- **The six request-type sidebar shortcuts (Full Review, Security Audit,
  Compliance Check, Performance, Impact Analysis, Explain Code) — CUT.**
  A previous revision claimed these were stripped by export corruption,
  citing six empty `<li>` elements at `settings_connected.html:143-162`,
  and instructed the implementer to obtain a clean re-export and "confirm
  in the live preview." That has now been done with the material in the
  repo: **`chat.png` and `settings_connected.png` are the rendered
  previews, and neither shows any shortcut** — `chat.png` goes straight
  from Past Conversations to empty space, and `settings_connected.png`
  shows a completely empty sidebar middle. HTML and PNG agree. The
  corruption theory was also self-inconsistent: the identical blank-slot
  signature appears where the same section declared elements
  "deliberately removed and resolved" (Webhooks panel
  `settings.html:251`; per-repo `link_off` `settings.html:229,245`;
  Plan/Role `settings.html:266`).
  **Consequence:** the composer's request-type dropdown is the only
  request-type selector; use Section 2's label table for its 7 options.
  `Sidebar` contains New Conversation + Past Conversations + the
  Settings/Account footer links, nothing else. Section 8.2 (shortcut
  behavior) has been deleted accordingly.
- **"Run Analysis" — CUT.** A previous revision listed it as real and
  claimed it "appears in `settings_connected.html`'s header." **It appears
  in no file:** a grep for `Run Analysis` across all five HTML files
  returns zero matches, and it renders in none of the five PNGs. Both
  Settings variants have a *blank* trailing-actions slot
  (`settings.html:175`, `settings_connected.html:193`) — neither holds a
  button. **Consequence:** the composer's send button is the only review
  trigger. Removed from §8's `TopBar`, which is now
  `RepoDropdown + BranchDropdown` only.
- **Composer "Attach file" / "Code snippet" buttons — CUT.** Both
  `<button>` elements at `chat.html:281-286` are entirely empty (no inner
  `<span>` at all, contrary to an earlier description), and `chat.png`
  shows only the send button. Applying the export-fidelity rule
  consistently, they are not built. **Consequence:** `diff_content` has no
  UI path (Section 2/4) — this is accepted, not a gap to patch.
- **"System Normal" health badge — already absent.** Previously listed as
  "still decorative." Grep returns zero matches in all five files. Nothing
  to cut; the claim was stale. (The notification bell `chat.html:132` and
  the `cmd+k` hint `chat.html:294` **are** present — see §7.5.)
- **Account card "Plan" / "Role"** — absent from the export
  (`settings.html:266` is a blank slot). Stay cut; no backing anywhere.
- **Jira "Auto-link PRs" / "Sync issue status on merge" checkboxes** —
  absent. Stay cut; no per-repo Jira automation exists.
- **Webhook Activity log panel** — absent; both Settings variants have an
  empty `<!-- Webhooks Dashboard -->` comment (`settings.html:250-251`,
  `settings_connected.html:266-267`). Stay cut.
- **Per-repo "Disconnect" (`link_off`) in the repo list** — absent
  (`settings.html:229,245` are blank slots). Stay cut. Note `link_off`
  *does* legitimately appear once, on the Jira card
  (`settings_connected.html:303`) — that one stays.
- **"Pull Request | Branch | Repository" top tabs** — absent from all
  screens. Stay cut.

### 7.4 Fabricated content present in the export — do not wire

Each of these renders in the export but has no backend. Cut or treat as
local-only, per the note.

| Element | Location | Reality | Action |
|---|---|---|---|
| Repo "Active" / "Paused" badges | `settings.html:227,243`; `settings_connected.html:245,260` | `RepoWorkspace` has no pause concept (`models.py:12-22`) | Cut the badge, or scope pause tracking as new backend work |
| "Last scanned: 10 mins ago" | `settings.html:222,238`; `settings_connected.html:240,255` | `last_requested_at`/`updated_at` exist (`models.py:20,22`) but **no endpoint exposes them** | Cut, or show the client-side registration timestamp and label it as local |
| "Search settings…" input | `settings.html:169`; `settings_connected.html:188` | no search endpoint | Frontend-only filter over rendered settings, or cut |
| Webhook URL `https://api.reviewmind.io/hooks/v1/trigger?token=gen_...` + Copy button | `onboarding.html:252-255` | Fabricated domain **and** a token-generation concept with no backend. The real inbound route is `POST /api/v1/webhook` requiring an HMAC `X-Hub-Signature-256` (`webhooks.py:28`) | Replace with static instructions naming the real path + manual GitHub setup, or cut the block |
| "Connect Webhook" button | `onboarding.html:259` | no webhook-registration endpoint (Section 3) | No-op placeholder clearly labelled, or cut |
| Onboarding `Indexed` / `Indexing…` states | `onboarding.html:221,231` | `GraphSnapshot.status` exists (`models.py:29`) but is exposed by no endpoint | Collapse to binary registered/not-registered per §4 |
| Fabricated placeholder data (repo names `core-api-v2`, `acme-corp/core-api`; messages; branch `feature/auth-refactor`; username `dev-lead-42`; avatar URLs; `v2.4.1-stable`) | all screens | static Stitch filler | Replace with real state/props; ship no placeholder strings |

### 7.5 Decorative — keep only if free

- **Notification bell** (`chat.html:132`, both Settings) — no notification
  system exists. Render inert with no badge, or cut. Do not invent a feed.
- **`cmd+k` hint** (`chat.html:294`) — a command palette can legitimately
  be frontend-only, triggering existing actions (New Conversation, switch
  request type). If you don't build the palette, cut the hint rather than
  advertising a shortcut that does nothing.
- **`help` button** (`chat.html:134`, both Settings) — no target defined.
  Inert or cut.
- **Composer placeholder "…or @mention an agent"** (`chat.html:278`) — no
  `@mention` parsing exists or is specified. Either drop the phrase, or
  implement it as pure local state (typing `@security` pre-selects
  `security_question` in the dropdown — no backend involvement). Do not
  imply server-side routing.

### 7.6 Unresolved export inconsistencies — decide once, before building

- **Sidebar diverges between screens.** `chat.html:140` uses `<aside>`,
  an **outlined** New Conversation button
  (`border border-primary-fixed-dim`), brand icon `psychology`
  (`chat.html:144`), and includes Past Conversations. Both Settings
  variants use `<nav>` (`settings.html:123`), a **solid** button
  (`bg-primary-container`), brand icon `neurology`
  (`settings.html:128`), and have **no** Past Conversations.
  **Decision: `chat.html`'s variant is canonical.** Build one `Sidebar`
  component — `<aside>`, outlined CTA, `psychology` icon, Past
  Conversations included — and render it identically on chat and Settings.
  A shared persistent sidebar is the correct SPA behavior and avoids two
  divergent components.
- **`settings_connected.html` has six empty `<li>`; `settings.html` has an
  empty container with none** (`settings.html:142-144`). With the shortcuts
  cut, both collapse to the same thing; noted only so the two files aren't
  mistaken for structurally different shells when merged into one
  component.
- **Jira card icon differs between states** — `deployed_code` in a solid
  `#0052CC` 10×10 box (`settings.html:274-276`) vs `task_alt` in a
  `#0052CC`/10 8×8 box (`settings_connected.html:289-291`). Same component,
  two states; pick one treatment (recommend the connected variant's, which
  is tonally consistent with the rest of the card set).
- **Sidebar "Account" link** (`chat.html:180-183`, both Settings) has no
  destination in §8's page list. Route it to Settings (where `AccountCard`
  lives) or cut the link.
- **Onboarding "Skip Onboarding" / "Complete Setup"**
  (`onboarding.html:187,268`) have no defined destination and no
  persistence target — there is no user/settings table. Route both to the
  main chat screen and store an "onboarding seen" flag locally only;
  Settings must remain reachable so onboarding can be revisited.
- **Fixed-viewport artifacts must be dropped.** `chat.html:1` hardcodes
  `style="width: 1280px; height: 1024px; overflow: hidden"` on `<html>`,
  and four screens set `overflow-hidden` on `<body>`. These are Stitch
  canvas artifacts, not design intent — remove them during the responsive
  pass (Stage 5c), or the PWA will be unusable on a phone.

### 7.7 Major — the "Agent Working Feed" finding cards aren't buildable as shown

`chat.html:202-264` shows rich per-agent-attributed finding cards
mid-stream ("SecurityAgent → Potential Vulnerability Detected: hardcoded
secret…" with a line-numbered code snippet) alongside pseudo-terminal lines
like `> running SAST scanner...` (`chat.html:234`). Per Section 5 this
splits into two problems — one resolved, one not:

- **Tool-call activity lines — resolvable, near-live.** Build the live
  per-agent log lines from polled `tool_calls` (Section 2/4), using real
  `tool_name`/`agent_name` values only. **There is no "SAST scanner" tool
  anywhere in this backend** — the real tool inventory is
  `tool_lists.py:14-150`. Never render an invented tool label.
- **Finding-card content — still not resolvable.** Title / severity /
  description / evidence / recommendation exist only in the single combined
  `result` returned *after* the whole review finishes, with no per-agent
  attribution (Section 5).

**Resolution:** during the "working" phase render per-agent log lines from
live `tool_calls`. Render findings once, as part of the final assistant
message from `POST /api/v1/review`'s own response, as **one combined list
grouped by severity** (§5.1's ordering) — never grouped or attributed by
agent. The code-snippet treatment in the export can be reused for
`AgentFinding.evidence` strings, but only when evidence actually contains
code; do not synthesize line numbers. If per-agent attribution matters for
the product, that is new backend work (exposing
`ReviewResult.per_agent`) — do not fake it by guessing which finding
"sounds like" a Security vs Performance issue.

### 7.8 Atlassian OAuth — build the shell, stub the wiring

The export shows a complete per-user OAuth pattern, and it is the intended
target direction: onboarding has an "OAuth 2.0" badge + "Requires
authorization" + "Connect Atlassian" (`onboarding.html:265`); Settings has
both states — not-connected ("Sync issues and workflows", full-width
"Connect Atlassian", "Requires OAuth 2.0 authorization" caption,
`settings.html:279-288`) and connected ("Active" badge, "Connected to
acme-corp.atlassian.net", Disconnect + Configure,
`settings_connected.html:293-307`).

The shape is fine to build. Two constraints (per Section 3/4): **no real
redirect** — `/auth/atlassian/authorize` does not exist, so "Connect
Atlassian" is a clearly-labelled placeholder; and **no reload-surviving
connected state** — there is no token storage, so a refresh must show
"not connected" again. "Configure" has no defined behavior anywhere and
stays a no-op placeholder.
---

## 8. Recommended frontend architecture (not existing code — a proposal)

Nothing below is grounded in an existing frontend codebase, because there
isn't one yet — this is a recommended structure, not a verified fact like
Sections 2–7. Deviate if OpenCode has a good reason, but keep the component
names already established in Section 1 (`Sidebar`, `ChatThread`,
`MessageComposer`, `RepoDropdown`, `BranchDropdown`, `EventFeed`) rather than
inventing new ones for the same things.

```
frontend/
├── public/
│   ├── manifest.json                 # PWA manifest
│   └── icons/                        # maskable + regular icon set
├── src/
│   ├── main.tsx                      # entry point, mounts <App>, registers SW
│   ├── App.tsx                       # router root — SignIn / Onboarding / MainChat / Settings
│   ├── api/                          # one file per Section 2 endpoint group, thin fetch wrappers only
│   │   ├── client.ts                 # base fetch wrapper — relative base `/api/v1` (§9.4), error mapping (§8.3)
│   │   ├── repos.ts                  # POST /api/v1/repos, GET /api/v1/repos/{repo_id:path}/branches
│   │   ├── conversations.ts          # POST /api/v1/conversations, POST /api/v1/conversations/{id}/message
│   │   ├── review.ts                 # POST /api/v1/review
│   │   └── reviewStatus.ts           # GET /api/v1/reviews/running, GET /api/v1/reviews/{session_id}
│   ├── types/
│   │   └── api.ts                    # TS interfaces mirroring Section 2 exactly — see Section 9
│   ├── hooks/
│   │   ├── useReviewTurn.ts          # the two-call send sequence (Section 2) — the ONLY place it lives
│   │   ├── useBranchReadiness.ts     # the 425-retry pattern (Section 4)
│   │   └── useReviewProgress.ts      # polls tool_calls while a review runs (Section 2/4, NEW) — never the answer source
│   ├── state/                        # context, or a small store lib — OpenCode's choice
│   │   ├── identity.ts               # mock user_id, generated/stored client-side (Section 3/4)
│   │   ├── activeRepo.ts             # selected repo_id/branch, registration/build progress
│   │   └── conversationCache.ts      # IndexedDB-backed local conversation list (Section 4)
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx           # New Conversation + Past Conversations + Settings/Account
│   │   │   │                         # footer. NO request-type shortcuts (cut, §7.3).
│   │   │   │                         # chat.html's variant is canonical (§7.6); shared by all screens.
│   │   │   └── TopBar.tsx            # RepoDropdown + BranchDropdown ONLY (no "Run Analysis", §7.3)
│   │   ├── chat/
│   │   │   ├── ChatThread.tsx
│   │   │   ├── MessageComposer.tsx   # + request-type dropdown (the ONLY selector, §2) + send.
│   │   │   │                         # No attach/snippet buttons (cut, §7.3) → no diff_content path.
│   │   │   ├── EventFeed.tsx         # live tool_calls while running — Section 4/5/6 rules apply
│   │   │   └── FindingsList.tsx      # final result, ONE list grouped by severity (§5.1), never by agent
│   │   ├── repo/
│   │   │   ├── RepoDropdown.tsx      # from local registration cache (§4) — no GET /api/v1/repos exists
│   │   │   └── BranchDropdown.tsx    # + manual-entry fallback (Section 6)
│   │   ├── onboarding/
│   │   │   ├── ConnectRepoStep.tsx
│   │   │   ├── WebhookStep.tsx       # fabricated URL/token cut (§7.4) — static instructions only
│   │   │   └── JiraStatusCard.tsx    # OAuth connect/disconnect shell, stubbed (§7.8)
│   │   └── settings/
│   │       ├── ConnectedRepos.tsx    # local cache (§4); Active/Paused + "Last scanned" cut (§7.4)
│   │       └── AccountCard.tsx       # username + avatar only (Plan/Role absent, §7.3)
│   ├── pages/
│   │   ├── SignIn.tsx
│   │   ├── Onboarding.tsx
│   │   ├── MainChat.tsx
│   │   └── Settings.tsx
│   └── styles/
│       └── tailwind.config.ts        # ported from Stitch's inline config — see Section 9.3
├── index.html
├── vite.config.ts                    # React + vite-plugin-pwa + DEV PROXY (§8.4, §9.4)
├── package.json
└── tsconfig.json
```

### 8.1 End-to-end data flow — a full chat turn

Ties Sections 2, 4, 5, 6, and 7 into one sequence:

1. **Repo selection:** `RepoDropdown` lists repos from the local
   registration cache (§4 — no `GET /api/v1/repos` exists). Registering a
   new one fires `POST /api/v1/repos`, shows a local "registering…" state —
   no way to know when it's actually done except retrying (Section 3/4).
2. **Branch selection:** `BranchDropdown` calls
   `GET /api/v1/repos/{repo_id:path}/branches` and reads
   `response.branches` (the response is a **wrapped object**, §2), plus a
   manual-entry fallback (Section 6, pagination unverified). Handle 500 here
   as well as 404 (§2).
3. **New conversation:** `POST /api/v1/conversations {repo_id, user_id}` →
   read `conversation_id` (not `id`) from the 4-key response; cache locally
   (§4 — no list endpoint exists).
4. **Sending a message** (`useReviewTurn`):
   a. Optimistically render the user's bubble.
   b. `POST /api/v1/conversations/{conversation_id}/message` — persists it,
      returns evidence only, **not** the reply (§2).
   c. `POST /api/v1/review` with `question` = the message content, the
      active `repo_id`/`branch`/`request_type` from the composer dropdown,
      and the same `conversation_id`/`user_id` — **this response is the
      reply** (§2). Omit `diff_content` (no UI path, §2/§4).
   d. While (c) is in flight: run `useReviewProgress` as a *separate*
      concurrent process — poll `GET /api/v1/reviews/running` for the
      session ID, then `GET /api/v1/reviews/{session_id}` for live
      `tool_calls` — to drive the "agent working" feed with real, if
      incomplete, data. This never substitutes for (c)'s own response; stop
      polling once (c) resolves. Real runs took 186s (one specialist) and
      455s (four) — switch to "still working, this can take several
      minutes" well before those marks (Section 6). For
      `request_type: "explain_question"` expect **zero** tool-call rows and
      do not treat that as a stall (§2, §5).
   e. On `425`: a branch build was needed — show "preparing this branch…",
      retry once it's likely done (Section 4).
   f. On success: parse `result` (**it is a JSON string** on this endpoint,
      §2) and render the findings as **one combined list ordered by
      severity** per §5.1 — not grouped or attributed by agent (§5/§7.7).
      Surface `parse_status` if it isn't `"ok"` (§5.2). The complete
      `timeline` is also available for a post-hoc record; don't re-animate
      it as if live.

### 8.2 Agent display names and colors

`tool_calls[].agent_name` and `timeline` keys return machine names, not the
export's labels (§5.3). The export supplies colors for only three agents
and uses names that don't exist in the API. This table is the mapping to
use; it is specified here because no export provides it.

| API `agent_name` | Display label | Color token |
|---|---|---|
| `compliance` | Compliance | `tertiary-fixed-dim` (`#e7c427`) |
| `security` | Security | `error` (`#ffb4ab`) |
| `performance` | Performance | `#ffb44d` (export's PerfAgent hue, `chat.html:253`) |
| `regression` | Regression | `secondary-fixed-dim` (`#c2c7d0`) |
| `fix_suggestion` | Fix Suggestion | `primary-fixed` (`#63f7ff`) |
| `context_agent` | Context | `outline` (`#849495`) |
| `aggregator` | Summary | `primary-container` (`#00f5ff`) |

Rules:
- The export's `Orchestrator` / `SecurityAgent` / `PerfAgent` labels
  (`chat.html:213,224,256`) are **placeholder text** — never render them.
- Any `agent_name` not in this table renders with the `outline` color and
  its raw name as the label. Never drop a row for an unknown agent.
- `#ffb44d` is not a design token — it is the one arbitrary hue carried
  over from the export deliberately (see §9.3's arbitrary-value rule).

### 8.3 Error-handling convention

| Status | Meaning | Suggested UI treatment |
|---|---|---|
| 400 | Bad request (unknown `request_type`, both/neither `branch`+`graph_commit_hash`, missing `user_id` with `conversation_id`) | Should never happen if §2's contracts are followed exactly — if it does, it's a frontend bug; log it, don't present it as transient |
| 404 | Unregistered repo / unknown branch / conversation not found / review not found or `user_id` mismatch | Distinct copy per context — "this repo isn't connected yet" vs "conversation not found, start a new one". Note a review 404 is deliberately ambiguous between "missing" and "not yours" (§2) |
| 425 | Graph/branch not ready | "Preparing this branch…" state + retry (Section 4) |
| 500 | Server error — **including a malformed GitHub payload on the branches endpoint** (§2) | Generic "something went wrong, try again" — no automatic retry loop. On the branch dropdown specifically, fall back to manual branch entry (Section 6) |

### 8.4 Config and the CORS/dev-proxy requirement

⚠️ **The backend has no CORS middleware** (Section 3, verified). A Vite dev
server on `:5173` calling an API on `:8000` is blocked by the browser on
every request, including preflight `OPTIONS`. **Resolution for Phase 5: a
Vite dev proxy — no backend change.**

- Set the API base to a **relative** path (`/api/v1`) so requests are
  same-origin from the browser's point of view, and let Vite proxy them.
  See §9.4 for the config.
- Keep the base configurable via `VITE_API_BASE_URL` (defaulting to
  `/api/v1`) so a deployed build can point elsewhere — it will differ
  across local/staging/prod and no phase doc pins one.
- **Production caveat that must be recorded, not silently inherited:** the
  proxy only exists in the Vite dev server. A production build served from
  a different origin than the API will fail for the same CORS reason.
  Production must either serve the built assets same-origin with the API or
  sit behind a reverse proxy that unifies the origin. Adding
  `CORSMiddleware` to `main.py` is the alternative, but that is a backend
  change outside Phase 5 scope and requires explicit authorization per
  `AGENTS.md` — do not do it as a side effect of frontend work.

---

## 9. Code skeletons

Structural patterns only — types are grounded in Section 2, the hook
skeleton operationalizes its most error-prone rule, the Tailwind note flags
a real production risk in the export. None of this is a claim about a
specific library's current exact API — verify that per Section 10.

### 9.1 API types (mirrors Section 2 exactly — don't add fields not listed there)

```typescript
export type RequestType =
  | "review" | "security_question" | "compliance_question"
  | "performance_question" | "impact_question" | "explain_question"
  | "any_question";

export interface Branch { name: string; sha: string; protected: boolean; }

// GET /api/v1/repos/{repo_id:path}/branches
// ⚠️ WRAPPED in an object — NOT a bare array (webhooks.py:176).
export interface BranchesResponse {
  repo_id: string;
  branches: Branch[];
}

// POST /api/v1/repos
export interface RegisterRepoResponse {
  status: "accepted";
  repo_id: string;
}

// POST /api/v1/conversations — exactly 4 keys (conversation.py:64-69).
// No `id`, no timestamps.
export interface CreateConversationResponse {
  conversation_id: number;
  repo_id: string;
  user_id: string;
  status: string;                      // "active" on create
}

// POST /api/v1/conversations/{conversation_id}/message
// ⚠️ This tool-call shape is DIFFERENT from ReviewToolCallItem below.
export interface ConversationToolCall {
  message_id: number;
  tool_name: string;
  tool_input: string | null;
  tool_output: string | null;
  tool_latency_ms: number | null;
  tool_status: "success" | "error" | null;
  id: number | null;
}

export interface RecallResult {
  message_id: number;
  role: string;
  snippet: string;
  created_at: string | null;
  score: number;
}

export interface MessageTurnResponse {
  conversation_id: number;
  user_message: string;
  context: {
    conversation_id: number;
    results: RecallResult[];
    error: string | null;
    latency_ms: number;
  } | null;
  tool_calls: ConversationToolCall[];   // ≤1 entry, always "search_messages"
}

export interface ReviewRequest {
  repo_id: string;
  graph_commit_hash?: string | null;   // exactly one of these two required
  branch?: string | null;              // (400 if both or neither)
  request_type: RequestType;
  diff_content?: string | null;        // optional; NO UI path in Phase 5 — always omit (§2/§4)
  question?: string | null;
  conversation_id?: number | null;
  user_id?: string | null;             // required (400) if conversation_id is set
}

export interface TimelineEntry { kind: "llm" | "tool"; name: string; duration_ms: number; }

export interface ReviewResponse {
  review_session_id: number;
  result: string;                                // JSON STRING — parse it (review.py:228)
  timeline: Record<string, TimelineEntry[]>;      // keyed by agent
  timeline_text: string;
}

// ⚠️ severity is an OPEN string, NOT a union — a live review returned
// info/warning/critical/high/medium/low. Nothing in the backend constrains
// it (agent_finding.py:18, report_schema.py:17). Normalize to lowercase and
// order critical > high > warning > medium > low > info; unknown values
// render with the `info` treatment. See §5.1.
export interface AgentFinding {
  severity: string;
  confidence: number;                  // constrained 0.0–1.0 (report_schema.py:18)
  title: string;
  description: string;
  evidence: string[];
  recommendation: string;
}

// The decoded shape of ReviewResponse.result.
export interface AggregatedOutput {
  agent_name: string;
  findings: AgentFinding[];
  parse_status: "ok" | "parse_failed" | "empty_output" | "fallback_from_specialists";
}

// --- Review status polling (Section 2) ---

export interface RunningReviewResponse {
  review_session_id: number | null;
  status: string | null;
  created_at?: string | null;          // ⚠️ ABSENT on no-match (review.py:282), not null
}

// VERIFIED against review_session_repository.py:169-175 — exactly 5 keys.
// No id, no review_session_id, no tool_input, no tool_output.
export interface ReviewToolCallItem {
  agent_name: string;
  tool_name: string;
  tool_latency_ms: number | null;
  tool_status: "success" | "error" | null;
  created_at: string | null;
}

export interface ReviewStatusResponse {
  review_session_id: number;
  status: "running" | "completed" | "failed" | null;   // null for legacy rows (models.py:45)
  repo_id: string;
  request_type: RequestType;
  created_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error: string | null;
  result: AggregatedOutput | null;     // ⚠️ PARSED dict here, unlike ReviewResponse.result
  tool_calls: ReviewToolCallItem[];    // ⚠️ unordered — sort on created_at (§2)
}
```

### 9.2 The send-turn sequence (Section 2's most error-prone rule, as code)

```typescript
// hooks/useReviewTurn.ts
async function sendTurn(
  conversationId: number, userId: string, repoId: string,
  content: string, requestType: RequestType, branch: string,
): Promise<{ response: ReviewResponse; result: AggregatedOutput }> {
  // Step 1 persists the message — its return value is NOT the reply.
  // POST /api/v1/conversations/{conversationId}/message
  await postConversationMessage(conversationId, { user_id: userId, repo_id: repoId, content });

  // Step 2 is the only call that answers the user.
  // POST /api/v1/review
  const response = await postReview({
    repo_id: repoId, branch, request_type: requestType,
    question: content, conversation_id: conversationId, user_id: userId,
    // diff_content deliberately omitted — no UI path in Phase 5 (§2/§4)
  });

  // `result` is a JSON STRING on this endpoint (review.py:228) — parse it.
  const result: AggregatedOutput = JSON.parse(response.result);
  return { response, result };
}
```

### 9.2b The progress-polling loop (Section 2/4 — supplementary, never authoritative)

```typescript
// hooks/useReviewProgress.ts
// Runs CONCURRENTLY with sendTurn above — does not replace it, does not
// gate the final answer on anything this returns. Caller stops this loop
// once sendTurn's own promise resolves, regardless of last poll result.
async function pollReviewProgress(
  conversationId: number, userId: string,
  onToolCalls: (calls: ReviewToolCallItem[]) => void,
  signal: AbortSignal,
) {
  let sessionId: number | null = null;
  while (!signal.aborted && sessionId === null) {
    // GET /api/v1/reviews/running?conversation_id=&user_id=
    const running = await getRunningReview(conversationId, userId);
    sessionId = running.review_session_id;
    if (sessionId === null) await sleep(1500); // review row not committed yet — small window, retry
  }
  while (!signal.aborted && sessionId !== null) {
    // GET /api/v1/reviews/{sessionId}?user_id=
    const status = await getReviewStatus(sessionId, userId);
    // Best-effort list; gaps expected. NOT guaranteed ordered — sort before display.
    const ordered = [...status.tool_calls].sort(
      (a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""),
    );
    onToolCalls(ordered);
    if (status.status !== "running") break; // stop; sendTurn's own response is still authoritative
    await sleep(2500); // a reasonable default — not a backend-mandated interval, tune as needed
  }
}
```

### 9.3 Tailwind: the export's CDN script is not production-safe

The Stitch export loads Tailwind via
`<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries">`
(the Play CDN, `chat.html:5`) and defines the custom design tokens in an
inline `<script id="tailwind-config">` block (`chat.html:6-99`).
**Tailwind's own documentation says the Play CDN is not for production** —
no purging, runtime compilation, large bundle. Port every token into a real
build and wire it through the Vite/PostCSS integration.

**Which source wins — this matters, they conflict.** `reviewmind/DESIGN.md`
and the exports' inline configs disagree:

| | `DESIGN.md` frontmatter | Export inline config (`chat.html:60-65`) |
|---|---|---|
| `rounded` | `sm .25 / DEFAULT .5 / md .75 / lg 1rem / xl 1.5rem` | `DEFAULT .25 / lg .5 / xl .75` — **no `sm`, no `md`** |

`DESIGN.md`'s prose also cites background/surface hexes (`#0A0E12`,
`#161B22`, `#30363D`, `#1C2128`, `#8B949E`) that match **no** token in the
config (`#101418`, `#1c2024`, `#3a494a`, `#262a2f`), and claims "a
consistent 8px (`rounded-md`) radius" — but `md` isn't defined in the export
config at all, so `rounded-md` (used at `settings.html:169,188`) silently
falls back to Tailwind's stock `0.375rem`/6px.

**Rules:**
1. **The exports' inline `tailwind.config` is authoritative for tokens.**
   Port its `colors`, `borderRadius`, `spacing`, `fontFamily`, and
   `fontSize` blocks verbatim.
2. **`DESIGN.md`'s prose hex values are non-normative** — treat that file as
   intent/rationale documentation, not as a token source. Its frontmatter
   `colors` block *does* match the inline config and is safe; its `rounded`
   block and prose hexes do not.
3. **Add `md: "0.375rem"` explicitly** to `borderRadius` so `rounded-md`
   resolves to a value chosen on purpose rather than by fallback. Do not
   remap `DEFAULT`/`lg`/`xl` — the markup depends on the export's values.
4. **Arbitrary hex values in the markup are kept verbatim.** The export
   mixes tokens with `bg-[#0A0E12]`, `bg-[#161B22]`, `border-[#30363D]`,
   `bg-[#0D1117]`, `hover:border-[#8B949E]`, `bg-[#1C2128]`, `bg-[#0052CC]`
   (Jira brand), `chat.html`'s code palette (`#c9d1d9`, `#8b949e`,
   `#ff7b72`, `#a5d6ff`) and `#ffb44d` (§8.2). Keep them as-is rather than
   guessing a token mapping — Tailwind compiles arbitrary values fine, and
   re-deriving them risks silent visual drift.
5. **One exception — resolve the background inconsistency.** `chat.html:187`
   uses the token `bg-surface-dim` (`#101418`) for the main canvas while
   both Settings screens use `bg-[#0A0E12]` (`settings.html:192`,
   `settings_connected.html:210`). Two different app backgrounds across
   screens is a bug, not intent. **Standardize on `bg-surface-dim`**
   (the token) for all main content areas.

```typescript
// styles/tailwind.config.ts — every key ported from the export's inline
// tailwind.config block unchanged; don't re-derive values from screenshots
// or from DESIGN.md's prose.
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: { /* ...all 40 tokens from chat.html:11-59, verbatim... */ },
      borderRadius: {
        DEFAULT: "0.25rem",
        md: "0.375rem",   // added deliberately — see rule 3
        lg: "0.5rem",
        xl: "0.75rem",
        full: "9999px",
      },
      spacing: { /* ...from chat.html:66-75... */ },
      fontFamily: { /* ...from chat.html:76-85... */ },
      fontSize: { /* ...from chat.html:86-95... */ },
    },
  },
};
```

⚠️ The snippet above assumes Tailwind **v3**'s JS-config model, which is
what the export was generated against. Tailwind v4 is CSS-first and has no
JS config by default — confirm the installed major version before porting
(Section 10).

### 9.4 Vite dev proxy (required — the backend has no CORS)

Without this, every request from the dev server is blocked by the browser
(Section 3, §8.4). Keep the API base **relative** so the proxy applies.

```typescript
// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [react(), VitePWA({ /* see Section 10 — verify current API shape */ })],
  server: {
    proxy: {
      // Same-origin from the browser's perspective → no CORS preflight.
      "/api/v1": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
```

```typescript
// api/client.ts
// Relative by default so the dev proxy applies; overridable for deploys.
const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
```

Production still needs same-origin serving or a reverse proxy — the dev
proxy does not ship with the build (§8.4).

---

## 10. External references for OpenCode

The "no guessing" rule in Section 1 covers backend contracts because
Sections 2–7 are already grounded in the phase docs. It extends to
frontend tooling too — library APIs move fast and this doc's author has a
training cutoff. **Verify current API shape via Context7 (if available) or
a live search before implementing any of these — don't assume the snippets
in Section 9 or anything remembered about these libraries is still exactly
current:**

- **Tailwind CSS — check the major version FIRST.** The Stitch export was
  generated against **v3**'s model: a JS `tailwind.config` object plus the
  Play CDN (`chat.html:5-99`). Tailwind **v4 is CSS-first** — configuration
  moves into CSS via `@theme`, there is no JS config by default, and the
  Vite integration is a dedicated `@tailwindcss/vite` plugin rather than a
  PostCSS step. §9.3's snippet assumes v3. Confirm which major you're
  installing before porting tokens, because the port differs completely
  between the two.
- **`vite-plugin-pwa`** — the PWA config surface (manifest injection,
  Workbox `runtimeCaching`, `registerType`) changes across versions.
  Confirmed current as of this doc: actively maintained, requires **Vite
  5+** (supports through Vite 8). Repo: `github.com/vite-pwa/vite-plugin-pwa`;
  React-specific guide at `docs/frameworks/react.md` in the same repo
  (covers the `virtual:pwa-register/react` hook for update/offline-ready
  state — needs `workbox-window` as a dev dependency).
- **Vite's `server.proxy`** — required for §9.4. Confirm the current option
  names (`target`, `changeOrigin`, `rewrite`) against Vite's server-options
  docs for the installed version.
- **A router** (e.g. `react-router`) — for the four screens/pages in
  Section 8's tree.
- **`idb`** (or equivalent) — for Section 4's local conversation and
  repo-registration caches; a thin promise wrapper avoids hand-rolling raw
  IndexedDB callback APIs.

---

## 11. Definition of Done — Phase 5

- [ ] All screens from the Stitch export are implemented as React components,
      routed correctly, PWA-installable (manifest + service worker).
- [ ] **Every request path includes the `/api/v1` prefix** — verified in the
      network tab, not just in source (Section 2).
- [ ] Every real API call matches Section 2 exactly, including the two
      shapes most easily got wrong: `GET .../branches` is read as
      `response.branches` (wrapped object), and `POST /api/v1/review`'s
      `result` is `JSON.parse`d (string), while
      `GET /api/v1/reviews/{id}`'s `result` is used directly (dict).
- [ ] **Vite dev proxy is configured** and the API base is relative, so no
      request is cross-origin in development (§8.4/§9.4). The production
      CORS caveat is recorded in the repo README or equivalent — not
      silently inherited.
- [ ] **`severity` is treated as an open string**, lowercase-normalized,
      ordered `critical > high > warning > medium > low > info`, with
      unknown values rendered rather than dropped (§5.1). Verified against a
      real review response, which returns more than three values.
- [ ] `parse_status` is read from the aggregated result and a non-`"ok"`
      value is surfaced as a caveat (§5.2).
- [ ] Agent names are mapped through §8.2's table — no export placeholder
      label ("Orchestrator", "SecurityAgent", "PerfAgent") appears anywhere,
      and an unknown `agent_name` still renders.
- [ ] Every item in Section 3 is either stubbed per Section 4 or explicitly
      called out as a follow-up backend task — none silently faked as if
      real. In particular both repo lists come from the local registration
      cache, since no `GET /api/v1/repos` exists.
- [ ] Every element in Section 7 is resolved — real, stubbed, cut, or
      explicitly scoped as new backend work — none built against a guessed
      endpoint. Specifically: **no sidebar request-type shortcuts, no "Run
      Analysis" button, no attach/code-snippet composer buttons** (§7.3),
      and none of §7.4's fabricated content is wired.
- [ ] `diff_content` is never sent (no UI path, §2/§4) and no diff input was
      invented to fill the gap.
- [ ] "Agent working" feed renders live tool activity from polled
      `tool_calls` using real names only, **sorted client-side on
      `created_at`** (the endpoint does not order them); the complete
      `timeline` and combined `result` are rendered from
      `POST /api/v1/review`'s own response once it resolves — never grouped
      or attributed by agent, and never sourced from the polling endpoints
      (§5/§7.7).
- [ ] The progress-polling loop never gates or supplies the final answer —
      confirmed by checking the code path, not just the UI behavior
      (Section 2's hard rule).
- [ ] Polling gaps are handled gracefully — no "stuck" state for a normal
      silent stretch, and **an empty feed for `explain_question` is treated
      as correct**, since that type dispatches no subagents (§2/§5/§6).
- [ ] Chat send flow performs both calls in Section 2 in order, and renders
      `POST /api/v1/review`'s response — not the message endpoint's — as the
      assistant's reply.
- [ ] Branch dropdown sourced only from
      `GET /api/v1/repos/{repo_id:path}/branches`, with a manual-entry
      fallback given unverified pagination, and it degrades to manual entry
      on a **500** as well as a 404 (§2/§6/§8.3).
- [ ] No claimed action (tool use, memory write, anything) is trusted from
      the final answer's text — only from `timeline`/`tool_calls` (Section 6).
- [ ] Long-running requests show a generic "still working" state — calibrated
      against real timings (186s single-specialist, 455s four-specialist),
      never a fixed ETA or an aggressive timeout implying failure (Section 6).
- [ ] Sign-in is display-name + client-generated `user_id` (`uuid`, persisted
      in `localStorage`), presented as **application identity only, not
      authentication** — no username/password, no OAuth, no "Secure
      Connection" implying a boundary that isn't there (decision 2, §4).
- [ ] GitHub PAT + per-repo webhook secret are collected on `POST
      /api/v1/repos`, stored **encrypted server-side only** (never in
      `localStorage`/IndexedDB, never in `.git/config`, never in logs or
      response bodies); the 7-assertion leak test in §11 passes (item 7).
- [ ] Jira is per-user `jira_url` + `jira_email` + `jira_api_token`
      (Basic `base64(email:token)`) — no global Jira credential is used for
      user work; `ALLOW_GLOBAL_CRED_FALLBACK=false`; the blocking Jira URL
      spike (item 5) passed before wiring (no 500 from `base_config.url`).
- [ ] GitHub PAT has **minimum scopes** `repo` (or `contents:read` +
      `pull-requests:read` + `metadata:read`) + `security_events:read` +
      `actions:read` — covering exactly the 12 read-only tools
      (`pull_request_read`, `get_file_contents`, `list_commits`,
      `search_code`, `list_branches`, `list/get_code_scanning_alert`,
      `list/get_dependabot_alert`, `actions_list/get/logs`) — verified
      from `tool_lists.py:36-63` + `branch_resolution.py:33` (item 6); no
      `admin:repo_hook` is requested (webhook is manual).
- [ ] One shared `Sidebar` component, `chat.html`'s variant, used on both
      chat and Settings (§7.6) — not two divergent sidebars.
- [ ] Tailwind is built via the Vite/PostCSS integration, not the Play CDN
      `<script>`; tokens ported from the **export's inline config** (not
      `DESIGN.md`'s prose hexes), and all main content areas use
      `bg-surface-dim` (§9.3).
- [ ] Stitch's fixed-viewport artifacts are removed — no `width: 1280px`
      on `<html>`, no stray `overflow-hidden` on `<body>` (§7.6).
- [ ] Current API shapes for Tailwind (**check the major version**),
      `vite-plugin-pwa`, and Vite's `server.proxy` are verified via Context7
      or a live search before implementing — not assumed from training data
      (Section 10).
- [ ] 425 from `POST /api/v1/review` triggers a visible "preparing this
      branch…" state and a retry path, not a silent failure.
- [ ] No Stitch placeholder data survives — no `core-api-v2`,
      `acme-corp/core-api`, `feature/auth-refactor`, `dev-lead-42`,
      `v2.4.1-stable`, or hardcoded example findings (§7.4).

---

## 12. Kickoff checklist — starting the actual OpenCode session

This phase now runs through the same three-subagent pipeline as Phases
1–4: `.opencode/agents/domain_architect.md` → `infra_engineer.md` →
`reviewer.md`, all rewritten for Phase 5 and grounded in this file. Each
agent's own file is its detailed task list — the checklist below is the
housekeeping and staging discipline around them, not a duplicate of it.

Housekeeping before you attach anything:

- [ ] **Rewrite the three Phase 5 agent files at `.opencode/agents/
      domain_architect.md` / `infra_engineer.md` / `reviewer.md` BEFORE
      starting the session.** A prior phase found the running session's
      agent config is cached at start, so fixing these mid-session doesn't
      take effect until the next one. As of this revision they were still
      scoped to **Phase 4** — verify each file's scope line says Phase 5.
- [ ] **Confirm `AGENTS.md` declares Phase 5 as the active phase.** It
      previously still pointed at Phase 3.
- [ ] Bundle this file + all five screen exports (**HTML and PNG**) +
      `reviewmind/DESIGN.md` + `PHASE_2.md` + `PHASE_3.md` into the session
      together (Section 1).
- [ ] Note for the session: the export is **complete and audited** — do not
      request a re-export. HTML and PNG agree on every screen; the elements
      previously suspected of being stripped are confirmed absent in the
      rendered PNGs and have been formally cut (§7.3).
- [ ] The two Settings exports are **two states of one component** (Jira
      connected / not connected), not two screens (§7.1).
- [ ] Let `domain_architect` run first and produce/approve its contracts
      (types, turn-sequence, state design, stub shapes) before
      `infra_engineer` starts Stage 5a.
- [ ] Kick off **Stage 5a only** — scaffold + HTML→React conversion, zero
      wiring — and stop there for `reviewer` before authorizing 5b.
- [ ] Keep a running log of this phase (append to `OPENCODE.md` or start
      `PHASE_5_LOG.md`), the same way Phases 1–4 were run.

What `reviewer` checks at each stage boundary, not just at the end:

- **After 5a:** component structure roughly matches Section 8 (or the
  deviation is explained) — no API calls exist yet. Confirm the cut elements
  (§7.3) were not built, and that no Stitch placeholder data remains.
- **After 5b:** open the network tab — confirm every path carries the
  `/api/v1` prefix, a chat turn fires the two calls from Section 2 in order,
  a `425` on an unbuilt branch shows the retry state, and the "agent
  working" feed shows real, live-polled `tool_calls` while running — then
  confirm the final answer came from `POST /api/v1/review`'s own response,
  not from the polling endpoints, by checking the code path directly.
- **After 5c:** walk Section 11 item by item as acceptance criteria, not a
  summary to skim.

Your own acceptance pass once it's built:

- Sign in (mock identity), skip onboarding, come back to it from Settings.
- Pick a branch that's never been built — confirm 425 → "preparing…" →
  retry actually works against the real backend, not a mocked delay.
- Send a message and watch the network tab: `GET /api/v1/reviews/running`
  polling until it gets a session ID, then `GET /api/v1/reviews/{id}`
  polling with a growing `tool_calls` list, while `POST /api/v1/review` is
  still pending — confirm the final rendered answer traces back to
  `POST /api/v1/review`'s response, not the last poll.
- Send a review against a repo with real findings and confirm severities
  outside `info`/`warning`/`critical` (e.g. `high`, `medium`, `low`) render
  correctly rather than being dropped (§5.1).
- Send an **Explain Code** request and confirm the empty activity feed reads
  as intentional, not stalled (§2/§6).
- Type a ticket key into a message (e.g. "check this against CLIP-3") in
  **Compliance Check** mode and confirm it reaches Compliance. Then do the
  same in **Full Review** mode and confirm it *also* forwards — `review` is
  a question-carrying type (`orchestrator_message.py:15-17`). An earlier
  revision of this doc wrongly asserted the opposite.
- In Settings → Jira, save `jira_url` + `jira_email` + `jira_api_token`,
  click Test connection, see `● Connected` (`get_current_user_account_id`
  200) then reload — credentials persist encrypted server-side (not in
  browser storage), and removing them shows `● Not connected` — no OAuth
  flow exists anywhere (decision 1).
- Check the **built** output (not the dev server) isn't loading Tailwind
  from the CDN script, and that main content areas use `bg-surface-dim`.
- Install it as a PWA on a phone and confirm it actually installs, opens
  standalone, and isn't stuck at a 1280px fixed width (§7.6).

---

## FINAL PHASE 5 Compliance / Gaps

**Final phase — no Phase 6. Every required capability is either already in the repo, added as minimal in-scope backend change, or manual setup.**

### Already supported
- 8 routes under /api/v1, POST /review sync + two polls, branches wrapped object, ReviewSession/ReviewToolCall, UserTokenMiddleware Basic/Bearer/Token (0.23.0), CRG build/fetch, 12 GitHub read-only tools, LangMem namespaces.

### Minimal backend changes (no larger architecture)
1. RepoCredential vault (repo_id PK, owning_user_id, repo_url_encrypted, github_pat_encrypted, webhook_secret_encrypted, jira fields) Fernet(CREDENTIAL_ENCRYPTION_KEY).
2. RepoWorkspace.repo_url TEXT.
3. GitRepoSource PAT-aware env (http.extraHeader, never token@ URL).
4. mcp_client_factory per-request github_pat_override + per-request Basic builder for Jira.
5. webhooks.py per-repo HMAC (lookup post-parse, 409 on hijack, no global fallback).
6. Jira URL one-line override if spike shows base_config.url leak.
7. POST /api/v1/integrations/jira/validate + save (write-only).

### Blocking spike (must pass before wiring)
Jira Basic header round-trip with placeholder global JIRA_URL. Pass=200 identity; fail=apply url override.

### Minimum PAT scopes (verified tool_lists.py:36-63 + branch_resolution.py:33)
repo (or contents:read + pull-requests:read + metadata:read) + security_events:read + actions:read. No admin:repo_hook (webhook manual).

### Leak test (7 assertions)
No credential in response, Fernet != plaintext, git config clean, logs redacted, nothing in localStorage/IndexedDB, token-in-URL rejected 400, only Authorization: Basic leaves.

### No-OAuth scan (narrow)
Fail if outside mcp_atlassian cache: \\boauth\\b, OAuth, OAUTH, github.*oauth, atlassian.*oauth, X-Atlassian-OAuth, /auth/atlassian, ALLOW_GLOBAL_CRED_FALLBACK, oauth toolset.

### Stitch changes you must make before 5a (26 changes, preserve design)
- sign_in 131-136 Continue with GitHub -> display-name input + Continue
- onboarding 211-239 repo list -> URL + PAT + webhook_secret inputs
- onboarding 252-259 fabricated api.reviewmind.io -> manual /api/v1/webhook instruction block
- Jira cards (both) -> URL/email/token form with Connected/Not connected/Error, OAuth 2.0/Configure deleted, Disconnect -> Remove credentials
- repo lists -> Connected + Webhook dot, Paused/Last scanned deleted
