"""Layer 2 API routes for stateful conversations (Phase 3).

- ``POST /conversations`` — open a conversation (user_id/repo_id in the body;
  there is no auth middleware, PHASE_3.md §9.5).
- ``POST /conversations/{id}/message`` — run a turn via the Application-layer
  use-case; the write path lives entirely in application/conversation_service.

Async routes; synchronous SQLite persistence is offloaded via asyncio.to_thread
so the event loop is never blocked (PHASE_3.md §1, AGENTS.md threadpool rule).
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from application.conversation_service.ports import (
    ContextAgentPort,
    ConversationAuditPort,
    ConversationStorePort,
)
from application.conversation_service.run_conversation_turn import (
    ConversationNotFoundError,
    run_conversation_turn,
)
from infrastructure.db.conversation_ports_adapters import (
    McpContextAgent,
    SQLModelConversationAudit,
)
from infrastructure.db.conversation_repository import SQLModelConversationRepository

logger = logging.getLogger(__name__)

router = APIRouter()

_repo: ConversationStorePort = SQLModelConversationRepository()
_audit: ConversationAuditPort = SQLModelConversationAudit()


class CreateConversationRequest(BaseModel):
    repo_id: str
    user_id: str


class MessageTurnRequest(BaseModel):
    user_id: str
    repo_id: str
    content: str


@router.post("/conversations")
async def create_conversation(body: CreateConversationRequest) -> dict:
    conversation = await asyncio.to_thread(
        _repo.create_conversation, body.repo_id, body.user_id
    )
    return {
        "conversation_id": conversation.id,
        "repo_id": conversation.repo_id,
        "user_id": conversation.user_id,
        "status": conversation.status,
    }


@router.post("/conversations/{conversation_id}/message")
async def run_turn(conversation_id: int, body: MessageTurnRequest, request: Request) -> dict:
    context_agent: ContextAgentPort = McpContextAgent(request.app.state.mcp_client)
    try:
        outcome = await run_conversation_turn(
            conversation_id,
            body.user_id,
            body.repo_id,
            body.content,
            store=_repo,
            context_agent=context_agent,
            audit=_audit,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return outcome