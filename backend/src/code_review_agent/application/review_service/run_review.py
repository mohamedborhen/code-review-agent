"""Use-case service that routes a review request to the orchestrator port.

Async throughout — this phase's Application layer awaits directly, no
asyncio.run() bridge (unlike Phase 1's sync BackgroundTasks flow).
"""

from application.review_service.errors import UnknownRequestTypeError
from domain.entities.agent_finding import AgentInput, ReviewResult
from domain.review.review_orchestrator_port import ReviewOrchestratorPort
from domain.review.routing_policy import agents_for_request


async def run_review(
    review_input: AgentInput,
    orchestrator: ReviewOrchestratorPort,
) -> ReviewResult:
    agent_names = agents_for_request(review_input.request_type)
    if agent_names is None:
        raise UnknownRequestTypeError(review_input.request_type)
    return await orchestrator.run_review(review_input, agent_names)
