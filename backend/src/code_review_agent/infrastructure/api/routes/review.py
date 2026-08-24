"""POST /review — async, request-response (no streaming).

Flow (order is load-bearing, see PHASE_2.md DoD):
1. Validate request_type against the Routing Policy (400 on unknown).
2. PrepareReviewContextService (404 unknown repo_id, 425 graph not ready) —
   BEFORE any agent runs, and the resolved repo_root comes from the
   RepoWorkspace DB row, never from a guessed path.
3. Create the ReviewSession audit row.
4. Run orchestrator -> subagents -> aggregator via run_review (Application
   layer) against the shared MultiServerMCPClient from app.state.
5. Persist one AgentExecution row per routed subagent plus the aggregator row,
   all in the SAME Phase 1 SQLite DB with timezone-aware timestamps.
6. Exception boundary (required): a failure mid-review still writes an
   AgentExecution error row before the 500 is returned.

Phase 2 is async throughout: DB writes are wrapped in asyncio.to_thread so the
event loop is never blocked. PrepareReviewContextService is the documented
blessed sync exception (see AGENTS.md).

SECURITY: GET /reviews/running and GET /reviews/{session_id} enforce
user_id matching against the session's stored user_id. This is
self-asserted identity — not true authentication. Any caller can
claim any user_id. Consistent with the existing zero-auth model
project-wide. Do not expose to untrusted networks without adding
HTTPBearer/JWT auth middleware. Any future real auth work should
cover the whole API, not just these two routes.
"""

import asyncio
import dataclasses
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from application.graph_build_service.graph_readiness_service import GraphReadinessService
from application.repo_ingestion_service.ensure_branch_worktree import (
    EnsureBranchWorktreeService,
)
from application.review_service.errors import (
    GraphNotReadyError,
    RepoNotFoundError,
    UnknownRequestTypeError,
)
from application.review_service.prepare_review_context import PrepareReviewContextService
from application.review_service.run_review import run_review
from domain.entities.agent_finding import AgentInput, AgentOutput, ReviewResult
from domain.review.routing_policy import agents_for_request
from infrastructure.agents_runtime.capture import CaptureStore
from infrastructure.agents_runtime.middleware import render_timeline
from infrastructure.agents_runtime.orchestrator_runtime import OrchestratorRuntime
from infrastructure.api.models import ReviewRequest
from infrastructure.config import settings
from infrastructure.db.engine import engine
from infrastructure.db.graph_status_repository import SQLModelGraphStatusQuery
from infrastructure.db.models import AgentExecution, ReviewSession, ReviewToolCall
from infrastructure.db.repo_workspace_repository import SQLModelRepoWorkspaceRepository
from infrastructure.db.review_tool_call_repository import ReviewToolCallRepository
from infrastructure.event_bus.log_event_bus import log_event
from infrastructure.graph_builder.crg_mcp_adapter import CRGMcpAdapter
from infrastructure.mcp_clients.branch_resolution import (
    BranchNotFoundError,
    resolve_branch_to_commit,
)
from infrastructure.repo_source.git_repo_source import GitRepoSource
from infrastructure.workspace.workspace_lock import acquire_workspace_lock, try_acquire_lock

logger = logging.getLogger(__name__)

router = APIRouter()

# Layer 2 is the composition root: the route wires the (stateless) DB adapters
# into Phase 1's GraphReadinessService and the review pre-flight use-case. Each
# call opens its own Session, so a module-level instance is safe.
_prepare_context = PrepareReviewContextService(
    SQLModelRepoWorkspaceRepository(),
    GraphReadinessService(SQLModelGraphStatusQuery()),
)

_repo_store = SQLModelRepoWorkspaceRepository()

_ensure_worktree = EnsureBranchWorktreeService(
    GitRepoSource(),
    CRGMcpAdapter(settings.crg_server_url),
    SQLModelRepoWorkspaceRepository(),
    settings.workspace_root,
    acquire_workspace_lock,
)

_tool_call_repo = ReviewToolCallRepository()


@router.post("/review")
async def review(
    request: Request, body: ReviewRequest, background_tasks: BackgroundTasks
) -> dict:
    if agents_for_request(body.request_type) is None:
        raise HTTPException(status_code=400, detail=f"Unknown request_type: {body.request_type}")

    _validate_branch_or_hash(body)
    _validate_conversation_identity(body)

    if body.branch is not None:
        owner, _, repo = body.repo_id.partition("/")
        try:
            resolved_commit = await resolve_branch_to_commit(
                request.app.state.mcp_client, owner, repo, body.branch
            )
        except BranchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    else:
        resolved_commit = body.graph_commit_hash

    try:
        repo_root = _prepare_context.execute(
            body.repo_id, resolved_commit, branch=body.branch
        )
    except RepoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GraphNotReadyError as exc:
        if body.branch is not None:
            if try_acquire_lock(settings.workspace_root, body.repo_id, body.branch):
                background_tasks.add_task(
                    _ensure_worktree.execute, body.repo_id, body.branch, resolved_commit
                )
        # NOTE: return a Response (not raise HTTPException) so the background
        # worktree build actually runs — FastAPI attaches BackgroundTasks only
        # on the normal return path; raising discards them silently.
        response = JSONResponse(
            status_code=425, content={"detail": "Graph not ready for this commit yet"}
        )
        response.background = background_tasks
        return response

    # Success path — refresh the eviction LRU recency signal (§11). Touched
    # here (not in the pre-flight use-case, which stays pure/side-effect-free).
    # The base-clone row's recency is kept fresh by webhook syncs' updated_at,
    # so only the per-branch rows need an explicit touch on access.
    if body.branch is not None:
        await asyncio.to_thread(
            _touch_recency, _repo_store, body.repo_id, body.branch
        )

    session_id = await asyncio.to_thread(_create_review_session, body, resolved_commit)

    review_input = AgentInput(
        repo_id=body.repo_id,
        graph_commit_hash=resolved_commit,
        request_type=body.request_type,
        diff_content=body.diff_content,
        repo_root=repo_root,
        question=body.question,
        conversation_id=body.conversation_id,
        user_id=body.user_id,
    )

    # D-12: lightweight MCP health probe.  If atlassian (or any server) died
    # since the last request, the static client holds stale sessions.  Rebuild
    # the client so subsequent get_tools() calls connect fresh.  The probe is
    # intentionally cheap — a single get_tools() call that succeeds or fails
    # fast; full tool acquisition happens later inside scope_agent_tools.
    try:
        await request.app.state.mcp_client.get_tools(server_name="atlassian")
    except Exception:
        logger.warning("Atlassian MCP unreachable — rebuilding client (D-12)")
        from infrastructure.mcp_clients.mcp_client_factory import rebuild_mcp_client

        request.app.state.mcp_client = await rebuild_mcp_client()

    orchestrator = OrchestratorRuntime(
        request.app.state.mcp_client,
        review_session_id=session_id,
        memory_store=request.app.state.memory_store,
        tool_call_repo=_tool_call_repo,
    )

    start = time.monotonic()
    try:
        outcome = await run_review(review_input, orchestrator)
    except HTTPException:
        raise
    except UnknownRequestTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await asyncio.to_thread(_record_error_execution, session_id, exc)
        logger.error("Review failed for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="Review failed") from exc
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)

    # Durable conversation summary (PHASE_4.md §5.3) runs as a FastAPI
    # BackgroundTask AFTER the response is sent, so the summary LLM call never
    # extends this request's latency (review finding F2, deviation D-P4-4).
    # Best-effort by construction: the guard in OrchestratorRuntime logs any
    # failure and a summary failure can never fail the review.
    if review_input.conversation_id is not None:
        background_tasks.add_task(orchestrator.write_durable_conversation_summary, review_input)

    await asyncio.to_thread(_record_executions, session_id, outcome, duration_ms, orchestrator.capture)

    timeline = orchestrator.capture.consume_timeline()
    await log_event("timeline", content=render_timeline(timeline))

    return {
        "review_session_id": session_id,
        "result": json.dumps(dataclasses.asdict(outcome.aggregated)),
        "timeline": timeline,
        "timeline_text": render_timeline(timeline),
    }


def _validate_branch_or_hash(body: ReviewRequest) -> None:
    supplied = (body.branch is not None, body.graph_commit_hash is not None)
    if sum(supplied) != 1:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of 'branch' or 'graph_commit_hash'",
        )


def _validate_conversation_identity(body: ReviewRequest) -> None:
    """conversation_id makes historical context AVAILABLE (never mandatory
    recall); it requires caller-supplied user_id for the search_messages
    authorization check (PHASE_3.md §9.5)."""
    if body.conversation_id is not None and body.user_id is None:
        raise HTTPException(
            status_code=400,
            detail="user_id is required when conversation_id is provided",
        )


def _touch_recency(repo_store, repo_id: str, branch: str) -> None:
    """Best-effort LRU recency touch (§11) — must never fail the review flow.

    This is non-load-bearing bookkeeping: a failure (e.g. SQLite locked past
    busy_timeout) is logged and swallowed so the review still proceeds and
    writes its audit rows.
    """
    try:
        repo_store.touch_requested_at(repo_id, branch)
    except Exception as exc:  # noqa: BLE001 — bookkeeping, not load-bearing
        logger.warning("recency touch failed for %s@%s: %s", repo_id, branch, exc)


def _create_review_session(body: ReviewRequest, resolved_commit: str) -> int:
    with Session(engine) as session:
        row = ReviewSession(
            repo_id=body.repo_id,
            graph_commit_hash=resolved_commit,
            request_type=body.request_type,
            model=settings.review_model,
            status="running",
            expected_agents=json.dumps(agents_for_request(body.request_type) or []),
            conversation_id=body.conversation_id,
            user_id=body.user_id,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def _record_executions(
    session_id: int,
    outcome: ReviewResult,
    duration_ms: int,
    capture: CaptureStore,
) -> None:
    with Session(engine) as session:
        review_session = session.get(ReviewSession, session_id)
        if review_session is not None:
            review_session.status = "completed"
            review_session.duration_ms = duration_ms
            review_session.completed_at = datetime.now(timezone.utc)
            review_session.dispatched_agents = json.dumps(
                [per_agent.agent_name for per_agent in outcome.per_agent]
            )
        for per_agent in outcome.per_agent:
            session.add(
                AgentExecution(
                    review_session_id=session_id,
                    agent_name=per_agent.agent_name,
                    duration_ms=capture.consume_duration(per_agent.agent_name),
                    confidence=_max_confidence(per_agent),
                    model=capture.consume_model(per_agent.agent_name) or settings.review_model,
                    result=json.dumps(dataclasses.asdict(per_agent)),
                )
            )
        session.add(
            AgentExecution(
                review_session_id=session_id,
                agent_name=outcome.aggregated.agent_name,
                duration_ms=duration_ms,
                confidence=_max_confidence(outcome.aggregated),
                model=capture.consume_model("orchestrator") or settings.review_model,
                result=json.dumps(dataclasses.asdict(outcome.aggregated)),
            )
        )
        session.commit()


def _record_error_execution(session_id: int, exc: Exception) -> None:
    with Session(engine) as session:
        review_session = session.get(ReviewSession, session_id)
        if review_session is not None:
            review_session.status = "failed"
            review_session.error = str(exc)
        session.add(
            AgentExecution(
                review_session_id=session_id,
                agent_name="orchestrator",
                duration_ms=0,
                result=json.dumps({"status": "error", "error": str(exc)}),
            )
        )
        session.commit()


def _max_confidence(agent_output: AgentOutput) -> float | None:
    if not agent_output.findings:
        return None
    return max(f.confidence for f in agent_output.findings)


# ---------------------------------------------------------------------------
# GET /reviews/running and GET /reviews/{session_id} — review status endpoints
# ---------------------------------------------------------------------------


@router.get("/reviews/running")
async def find_running_review(conversation_id: int, user_id: str) -> dict:
    """Find the currently running review for a conversation.

    UNAUTHENTICATED / DEV-ONLY — self-asserted user_id matching, not true auth.
    Requires conversation_id + user_id. user_id must match the session's user_id.
    conversation_id is required (each conversation has exactly one active review).
    """
    row = await asyncio.to_thread(_find_running_review, conversation_id, user_id)
    if row is None:
        return {"review_session_id": None, "status": None}
    return {
        "review_session_id": row.id,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/reviews/{session_id}")
async def get_review(session_id: int, user_id: str) -> dict:
    """Get review status, result, and tool-call metadata.

    UNAUTHENTICATED / DEV-ONLY — self-asserted user_id matching, not true auth.
    Requires user_id query param. user_id must match the session's user_id.
    """
    row = await asyncio.to_thread(_get_review_session, session_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Review not found")
    result = None
    if row.status == "completed":
        raw = await asyncio.to_thread(_get_aggregated_result, session_id)
        if raw is not None:
            result = json.loads(raw)
    tool_calls = await asyncio.to_thread(_get_tool_calls, session_id)
    return {
        "review_session_id": row.id,
        "status": row.status,
        "repo_id": row.repo_id,
        "request_type": row.request_type,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "duration_ms": row.duration_ms,
        "error": row.error,
        "result": result,
        "tool_calls": tool_calls,
    }


def _get_review_session(session_id: int, user_id: str) -> ReviewSession | None:
    """Load session ONLY if user_id matches. Returns None on mismatch."""
    with Session(engine) as s:
        row = s.get(ReviewSession, session_id)
        if row is None or row.user_id != user_id:
            return None
        return row


def _get_aggregated_result(session_id: int) -> str | None:
    with Session(engine) as s:
        row = s.exec(
            select(AgentExecution).where(
                AgentExecution.review_session_id == session_id,
                AgentExecution.agent_name == "aggregator",
            )
        ).first()
        return row.result if row else None


def _get_tool_calls(session_id: int) -> list[dict]:
    """Return tool-call metadata for a review session."""
    with Session(engine) as s:
        rows = s.exec(
            select(ReviewToolCall).where(ReviewToolCall.review_session_id == session_id)
        ).all()
        return [
            {
                "agent_name": r.agent_name,
                "tool_name": r.tool_name,
                "tool_latency_ms": r.tool_latency_ms,
                "tool_status": r.tool_status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def _find_running_review(conversation_id: int, user_id: str) -> ReviewSession | None:
    """Find running review for conversation, enforcing user_id match."""
    with Session(engine) as s:
        return s.exec(
            select(ReviewSession).where(
                ReviewSession.conversation_id == conversation_id,
                ReviewSession.user_id == user_id,
                ReviewSession.status == "running",
            ).order_by(ReviewSession.created_at.desc()).limit(1)
        ).first()
