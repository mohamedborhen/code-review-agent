# Async /review Architecture — Future Requirement

**Status:** Design document (not implemented)
**Date:** 2026-08-21

## Current State

`POST /review` is **synchronous** — it blocks for the full review duration (typically 2–5 minutes). The handler:

1. Validates input, resolves branch/commit
2. Prepares graph context (checkout, CRG build if stale)
3. Runs `OrchestratorRuntime.run_review()` — awaits the full multi-agent pipeline
4. Serializes results, records `AgentExecution` rows
5. Returns the complete `ReviewResponse`

The client connection is held open for the entire duration. No progress feedback, no cancellation, no partial results.

## Problem

A frontend cannot hold an HTTP connection for 5 minutes:
- Browsers timeout or show a spinner with no feedback
- No way to show per-agent progress (security running... performance running...)
- No way to cancel an in-flight review
- No retry on transient failures without re-running the entire review
- Load balancers may drop idle connections

## Proposed Architecture

### New Endpoints

| Method | Path | Purpose | Returns |
|--------|------|---------|---------|
| `POST /reviews` | Submit review | HTTP 202 Accepted | `{"review_id": "abc123", "status": "pending"}` |
| `GET /reviews/{id}` | Poll status | HTTP 200 | Status + partial results |
| `GET /reviews/{id}/events` | SSE stream | HTTP 200 (stream) | Real-time event stream |
| `DELETE /reviews/{id}` | Cancel review | HTTP 204 | — |

### POST /reviews (Submit)

```json
// Request (same body as POST /review)
{
  "repo_id": "mohamedborhen/credit-risk-analysis",
  "graph_commit_hash": "abc...",
  "request_type": "review",
  "question": "...",
  "conversation_id": 11,
  "idempotency_key": "optional-client-generated-key"
}

// Response
{
  "review_id": "rev_abc123",
  "status": "pending",
  "created_at": "2026-08-21T10:00:00Z"
}
```

The handler:
1. Validates input (same as current)
2. Creates a `ReviewSession` row with `status='pending'`
3. Schedules the review as a `BackgroundTask`
4. Returns HTTP 202 immediately

### GET /reviews/{id} (Poll Status)

```json
{
  "review_id": "rev_abc123",
  "status": "running",
  "agents_completed": ["compliance", "security"],
  "agents_pending": ["performance", "regression"],
  "elapsed_ms": 45000,
  "result": null
}
```

When `status='completed'`:
```json
{
  "review_id": "rev_abc123",
  "status": "completed",
  "elapsed_ms": 238500,
  "result": {
    "aggregated": { "agent_name": "aggregator", "findings": [...] },
    "per_agent": [...]
  }
}
```

### GET /reviews/{id}/events (SSE Stream)

Server-Sent Events stream of review lifecycle events:

```
event: agent_start
data: {"agent": "security", "timestamp": "..."}

event: agent_complete
data: {"agent": "security", "duration_ms": 111900, "finding_count": 2}

event: review_complete
data: {"review_id": "rev_abc123", "status": "completed"}
```

Events are sourced from the existing `review_events.log` log file, filtered by review session ID.

### DELETE /reviews/{id} (Cancel)

Sets `ReviewSession.status = 'cancelled'`. The background task checks this flag periodically and aborts if set. In-flight LLM calls are not cancelled (no mechanism for that with the current provider), but no further agents are dispatched.

## Implementation Considerations

### Task Queue

For the initial implementation, FastAPI `BackgroundTasks` is sufficient — the review runs in-process. For production scaling:

- **Redis + Celery/RQ** for distributed task execution
- **ReviewSession.status** already tracks lifecycle: `pending → running → completed | failed | cancelled`
- Idempotency: `POST /reviews` with `idempotency_key` checks for an existing session with the same key before creating a new one

### Progress Tracking

The existing `AgentExecution` table already records per-agent start/end times. The `GET /reviews/{id}` endpoint queries `AgentExecution WHERE review_session_id = :id` to determine which agents are complete.

### SSE Event Source

The existing `log_event_bus.py` emits events to `review_events.log`. For SSE, either:
1. Tail the log file (simple, works now)
2. Add an in-memory event queue per review session (cleaner, requires refactoring `log_event_bus`)

### Migration Path

Keep the synchronous `POST /review` for CLI and API consumers that need the full result in one call. Add `POST /reviews` as a parallel endpoint for frontend use. Both share the same `OrchestratorRuntime` and `ReviewSession` table.

## What NOT to Implement Now

This document captures the design for future implementation. The current synchronous `POST /review` remains the production endpoint. The async architecture will be implemented when the frontend is built (Phase 5+).
