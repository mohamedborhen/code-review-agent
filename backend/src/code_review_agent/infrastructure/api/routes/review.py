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
"""

import asyncio
import dataclasses
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import Session

from application.graph_build_service.graph_readiness_service import GraphReadinessService
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
from infrastructure.db.models import AgentExecution, ReviewSession
from infrastructure.db.repo_workspace_repository import SQLModelRepoWorkspaceRepository
from infrastructure.event_bus.log_event_bus import log_event

logger = logging.getLogger(__name__)

router = APIRouter()

# Layer 2 is the composition root: the route wires the (stateless) DB adapters
# into Phase 1's GraphReadinessService and the review pre-flight use-case. Each
# call opens its own Session, so a module-level instance is safe.
_prepare_context = PrepareReviewContextService(
    SQLModelRepoWorkspaceRepository(),
    GraphReadinessService(SQLModelGraphStatusQuery()),
)


@router.post("/review")
async def review(request: Request, body: ReviewRequest) -> dict:
    if agents_for_request(body.request_type) is None:
        raise HTTPException(status_code=400, detail=f"Unknown request_type: {body.request_type}")

    try:
        repo_root = _prepare_context.execute(body.repo_id, body.graph_commit_hash)
    except RepoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GraphNotReadyError as exc:
        raise HTTPException(status_code=425, detail="Graph not ready for this commit yet") from exc

    session_id = await asyncio.to_thread(_create_review_session, body)

    review_input = AgentInput(
        repo_id=body.repo_id,
        graph_commit_hash=body.graph_commit_hash,
        request_type=body.request_type,
        diff_content=body.diff_content,
        repo_root=repo_root,
        question=body.question,
    )

    orchestrator = OrchestratorRuntime(request.app.state.mcp_client)

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

    await asyncio.to_thread(_record_executions, session_id, outcome, duration_ms, orchestrator.capture)

    timeline = orchestrator.capture.consume_timeline()
    await log_event("timeline", content=render_timeline(timeline))

    return {
        "review_session_id": session_id,
        "result": json.dumps(dataclasses.asdict(outcome.aggregated)),
        "timeline": timeline,
        "timeline_text": render_timeline(timeline),
    }


def _create_review_session(body: ReviewRequest) -> int:
    with Session(engine) as session:
        row = ReviewSession(
            repo_id=body.repo_id,
            graph_commit_hash=body.graph_commit_hash,
            request_type=body.request_type,
            model=settings.review_model,
            status="running",
            expected_agents=json.dumps(agents_for_request(body.request_type) or []),
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
