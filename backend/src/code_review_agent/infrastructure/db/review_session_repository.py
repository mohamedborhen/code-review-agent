"""ReviewSession + AgentExecution persistence for the /review routes.

Extracted from the route module so routes stay HTTP-only and all inline
Session(engine) DB blocks live in one Layer 2 adapter. Each method opens its
own Session — the class is stateless and safe as a module-level singleton.
All methods are sync; call via asyncio.to_thread from async routes.
"""

import dataclasses
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from domain.entities.agent_finding import AgentOutput
from infrastructure.db.engine import engine
from infrastructure.db.models import AgentExecution, ReviewSession, ReviewToolCall


def _max_confidence(agent_output: AgentOutput) -> float | None:
    if not agent_output.findings:
        return None
    return max(f.confidence for f in agent_output.findings)


class ReviewSessionRepository:
    def create(
        self,
        *,
        repo_id: str,
        graph_commit_hash: str,
        request_type: str,
        model: str | None,
        expected_agents: list[str],
        conversation_id: int | None = None,
        user_id: str | None = None,
    ) -> int:
        """Create a ReviewSession row with status="running"; return its id."""
        with Session(engine) as session:
            row = ReviewSession(
                repo_id=repo_id,
                graph_commit_hash=graph_commit_hash,
                request_type=request_type,
                model=model,
                status="running",
                expected_agents=json.dumps(expected_agents),
                conversation_id=conversation_id,
                user_id=user_id,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    def get(self, session_id: int, user_id: str) -> ReviewSession | None:
        """Load session ONLY if user_id matches. Returns None on mismatch."""
        with Session(engine) as s:
            row = s.get(ReviewSession, session_id)
            if row is None or row.user_id != user_id:
                return None
            return row

    def find_running(self, conversation_id: int, user_id: str) -> ReviewSession | None:
        """Find running review for conversation, enforcing user_id match."""
        with Session(engine) as s:
            return s.exec(
                select(ReviewSession).where(
                    ReviewSession.conversation_id == conversation_id,
                    ReviewSession.user_id == user_id,
                    ReviewSession.status == "running",
                ).order_by(ReviewSession.created_at.desc()).limit(1)
            ).first()

    def mark_completed(
        self, session_id: int, *, duration_ms: int, dispatched_agents: list[str]
    ) -> None:
        with Session(engine) as session:
            review_session = session.get(ReviewSession, session_id)
            if review_session is not None:
                review_session.status = "completed"
                review_session.duration_ms = duration_ms
                review_session.completed_at = datetime.now(timezone.utc)
                review_session.dispatched_agents = json.dumps(dispatched_agents)
            session.commit()

    def mark_failed(self, session_id: int, error: Exception) -> None:
        """Mark the session failed and persist an orchestrator error execution.

        Required exception boundary: a failure mid-review still writes an
        AgentExecution error row before the 500 is returned.
        """
        with Session(engine) as session:
            review_session = session.get(ReviewSession, session_id)
            if review_session is not None:
                review_session.status = "failed"
                review_session.error = str(error)
            session.add(
                AgentExecution(
                    review_session_id=session_id,
                    agent_name="orchestrator",
                    duration_ms=0,
                    result=json.dumps({"status": "error", "error": str(error)}),
                )
            )
            session.commit()

    def record_executions(
        self,
        session_id: int,
        per_agent: list[AgentOutput],
        aggregated: AgentOutput,
        *,
        duration_ms: int,
        capture,
        model: str | None,
    ) -> None:
        """Persist one AgentExecution row per subagent plus the aggregator row,
        and mark the session completed — all in ONE transaction."""
        with Session(engine) as session:
            review_session = session.get(ReviewSession, session_id)
            if review_session is not None:
                review_session.status = "completed"
                review_session.duration_ms = duration_ms
                review_session.completed_at = datetime.now(timezone.utc)
                review_session.dispatched_agents = json.dumps(
                    [per_agent_row.agent_name for per_agent_row in per_agent]
                )
            for agent_output in per_agent:
                session.add(
                    AgentExecution(
                        review_session_id=session_id,
                        agent_name=agent_output.agent_name,
                        duration_ms=capture.consume_duration(agent_output.agent_name),
                        confidence=_max_confidence(agent_output),
                        model=capture.consume_model(agent_output.agent_name) or model,
                        result=json.dumps(dataclasses.asdict(agent_output)),
                    )
                )
            session.add(
                AgentExecution(
                    review_session_id=session_id,
                    agent_name=aggregated.agent_name,
                    duration_ms=duration_ms,
                    confidence=_max_confidence(aggregated),
                    model=capture.consume_model("orchestrator") or model,
                    result=json.dumps(dataclasses.asdict(aggregated)),
                )
            )
            session.commit()

    def get_aggregated_result(self, session_id: int) -> str | None:
        """Get the aggregator's AgentExecution result JSON for a session."""
        with Session(engine) as s:
            row = s.exec(
                select(AgentExecution).where(
                    AgentExecution.review_session_id == session_id,
                    AgentExecution.agent_name == "aggregator",
                )
            ).first()
            return row.result if row else None

    def get_tool_calls(self, session_id: int) -> list[dict]:
        """Return tool-call metadata dicts for a review session."""
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
