"""Layer 2 API routes for account restore (Phase 5, Decision 7 vault exception).

Provides read-only endpoints for verifying and restoring user accounts:
- ``GET /accounts/lookup`` — verify a user_id exists, return metadata
- ``GET /accounts/conversations`` — list all conversations for a user
- ``GET /accounts/repos`` — list all repos registered by a user (no credentials)

These endpoints enable account restore across browsers/sessions without
exposing other accounts or authentication. The user must explicitly provide
their user_id to restore their data.

UNAUTHENTICATED / DEV-ONLY — self-asserted user_id, consistent with the
existing zero-auth model (AGENTS.md Decision 2).
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, func, select

from infrastructure.db.engine import engine
from infrastructure.db.models import (
    Conversation,
    RepoCredential,
    ReviewSession,
    ReviewToolCall,
    AgentExecution,
    Message,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/accounts/lookup")
async def lookup_account(user_id: str = Query(..., description="User ID to verify")) -> dict:
    """Verify a user_id exists and return metadata.

    Returns 200 with metadata if the user has any conversations.
    Returns 404 if the user_id has no conversations in the database.
    """
    with Session(engine) as session:
        # Check if user has any conversations
        conversation_count = session.exec(
            select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
        ).one()

        if conversation_count == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Account not found: {user_id}",
            )

        # Count repos from RepoCredential
        repo_count = session.exec(
            select(func.count(RepoCredential.id)).where(
                RepoCredential.owning_user_id == user_id
            )
        ).one()

        # Count review sessions (only those with user_id matching)
        review_count = session.exec(
            select(func.count(ReviewSession.id)).where(
                ReviewSession.user_id == user_id
            )
        ).one()

    return {
        "exists": True,
        "user_id": user_id,
        "display_name": None,  # Not stored in backend per Decision 2
        "conversation_count": conversation_count,
        "repo_count": repo_count,
        "review_count": review_count,
    }


@router.get("/accounts/conversations")
async def list_conversations(user_id: str = Query(..., description="User ID")) -> dict:
    """List all conversations for a user.

    Returns conversations ordered by created_at DESC (newest first).
    Each conversation includes its messages count and latest review session.
    """
    with Session(engine) as session:
        conversations = session.exec(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
        ).all()

        result = []
        for conv in conversations:
            # Count messages in this conversation
            message_count = session.exec(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conv.id
                )
            ).one()

            # Get latest review session for this conversation
            latest_review = session.exec(
                select(ReviewSession)
                .where(
                    ReviewSession.conversation_id == conv.id,
                    ReviewSession.user_id == user_id,
                )
                .order_by(ReviewSession.created_at.desc())
                .limit(1)
            ).first()

            result.append({
                "conversation_id": conv.id,
                "repo_id": conv.repo_id,
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "message_count": message_count,
                "latest_review_id": latest_review.id if latest_review else None,
                "latest_review_status": latest_review.status if latest_review else None,
            })

    return {"conversations": result}


@router.get("/accounts/repos")
async def list_repos(user_id: str = Query(..., description="User ID")) -> dict:
    """List all repos registered by a user.

    Returns repo metadata WITHOUT credentials (security: Decision 7).
    Only returns repos where the user is the owning_user_id.
    """
    with Session(engine) as session:
        credentials = session.exec(
            select(RepoCredential)
            .where(RepoCredential.owning_user_id == user_id)
            .order_by(RepoCredential.created_at.desc())
        ).all()

        result = []
        for cred in credentials:
            result.append({
                "repo_id": cred.repo_id,
                "created_at": cred.created_at.isoformat() if cred.created_at else None,
                "has_github_pat": cred.github_pat_encrypted is not None,
                "has_webhook_secret": cred.webhook_secret_encrypted is not None,
                "has_jira_token": cred.jira_api_token_encrypted is not None,
            })

    return {"repos": result}


@router.get("/accounts/reviews")
async def list_reviews(user_id: str = Query(..., description="User ID")) -> dict:
    """List all review sessions for a user.

    Returns reviews with their aggregated result summary (findings count, not full content).
    Only returns reviews where user_id matches.
    """
    with Session(engine) as session:
        reviews = session.exec(
            select(ReviewSession)
            .where(ReviewSession.user_id == user_id)
            .order_by(ReviewSession.created_at.desc())
        ).all()

        result = []
        for review in reviews:
            # Get aggregated result to count findings
            aggregated = session.exec(
                select(AgentExecution)
                .where(
                    AgentExecution.review_session_id == review.id,
                    AgentExecution.agent_name == "aggregator",
                )
                .limit(1)
            ).first()

            finding_count = 0
            if aggregated and aggregated.result:
                try:
                    import json
                    data = json.loads(aggregated.result)
                    finding_count = len(data.get("findings", []))
                except (json.JSONDecodeError, AttributeError):
                    pass

            result.append({
                "review_session_id": review.id,
                "conversation_id": review.conversation_id,
                "repo_id": review.repo_id,
                "request_type": review.request_type,
                "status": review.status,
                "created_at": review.created_at.isoformat() if review.created_at else None,
                "completed_at": review.completed_at.isoformat() if review.completed_at else None,
                "duration_ms": review.duration_ms,
                "finding_count": finding_count,
            })

    return {"reviews": result}
