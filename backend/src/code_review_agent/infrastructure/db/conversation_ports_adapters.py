"""Adapters for the Layer 3 conversation ports (Phase 3).

- ``McpContextAgent`` implements ``ContextAgentPort``: calls the read-only
  Context Agent's ``search_messages`` tool via the shared client on
  ``app.state.mcp_client`` and parses the tool's JSON contract (PHASE_3.md §5).
- ``SQLModelConversationAudit`` implements ``ConversationAuditPort``: writes
  AgentExecution rows for context-agent invocations. NEVER logs message content
  or snippet text — only query/identity/counts/status (PHASE_3.md §7).
"""

import dataclasses
import json
import time

from sqlmodel import Session

from domain.entities.conversation_entity import ContextRetrieval, ContextRetrievalResult
from infrastructure.agents_runtime.subagents.context_agent_runtime import (
    search_conversation_context,
)
from infrastructure.db.engine import engine
from infrastructure.db.models import AgentExecution


class McpContextAgent:
    """ContextAgentPort implementation over the shared MultiServerMCPClient."""

    def __init__(self, mcp_client) -> None:
        self._mcp_client = mcp_client

    async def search_context(
        self,
        conversation_id: int,
        user_id: str,
        repo_id: str,
        query: str,
        limit: int = 10,
    ) -> ContextRetrieval:
        started = time.monotonic()
        raw = await search_conversation_context(
            self._mcp_client,
            conversation_id=conversation_id,
            user_id=user_id,
            repo_id=repo_id,
            query=query,
            limit=limit,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        if raw is None:
            return ContextRetrieval(
                conversation_id=conversation_id, error="unavailable", latency_ms=latency_ms
            )
        try:
            payload = json.loads(raw)
        except ValueError:
            return ContextRetrieval(
                conversation_id=conversation_id, error="invalid_response", latency_ms=latency_ms
            )
        if not isinstance(payload, dict):
            return ContextRetrieval(
                conversation_id=conversation_id, error="invalid_response", latency_ms=latency_ms
            )
        results = [
            ContextRetrievalResult(
                message_id=int(item["message_id"]),
                role=str(item.get("role", "")),
                snippet=str(item.get("snippet", "")),
                created_at=item.get("created_at"),
                score=float(item.get("score", 0.0)),
            )
            for item in payload.get("results", [])
            if isinstance(item, dict) and item.get("message_id") is not None
        ]
        return ContextRetrieval(
            conversation_id=conversation_id,
            results=results,
            error=payload.get("error"),
            latency_ms=latency_ms,
        )


class SQLModelConversationAudit:
    """ConversationAuditPort implementation (AgentExecution rows)."""

    def __init__(self, engine=engine) -> None:
        # Injectable engine for tests (see tests/test_repo_workspace_repository.py);
        # production callers use the shared global engine.
        self._engine = engine

    def record_context_invocation(
        self,
        conversation_id: int,
        query: str,
        results_count: int,
        latency_ms: int,
        status: str,
    ) -> None:
        # Audit payload records query + counts only — never message content or
        # snippet text (PHASE_3.md §7 Strict Privacy Rule).
        audit = dataclasses.asdict(
            _ContextInvocationAudit(
                query=query,
                conversation_id=conversation_id,
                results_count=results_count,
                latency_ms=latency_ms,
                status=status,
            )
        )
        with Session(self._engine) as session:
            session.add(
                AgentExecution(
                    review_session_id=None,
                    conversation_id=conversation_id,
                    agent_name="context_agent",
                    duration_ms=latency_ms,
                    result=json.dumps(audit),
                )
            )
            session.commit()


@dataclasses.dataclass
class _ContextInvocationAudit:
    query: str
    conversation_id: int
    results_count: int
    latency_ms: int
    status: str