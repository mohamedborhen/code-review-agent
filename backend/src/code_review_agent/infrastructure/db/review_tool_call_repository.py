"""Best-effort persistence for ReviewToolCall rows.

Fails silently — logging a warning — so that DB errors never break the review flow.
"""

import logging

from sqlmodel import Session

from infrastructure.db.engine import engine
from infrastructure.db.models import ReviewToolCall

logger = logging.getLogger(__name__)


class ReviewToolCallRepository:
    def add(self, call: ReviewToolCall) -> None:
        """Sync — call via asyncio.to_thread. Best-effort: never raises."""
        try:
            with Session(engine) as session:
                session.add(call)
                session.commit()
        except Exception:
            logger.warning(
                "ReviewToolCall persistence failed: agent=%s tool=%s",
                call.agent_name,
                call.tool_name,
                exc_info=True,
            )
