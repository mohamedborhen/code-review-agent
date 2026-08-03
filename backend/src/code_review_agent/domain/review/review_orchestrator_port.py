"""Layer 4 port for review orchestration.

Implemented by Layer 5 (infrastructure/agents_runtime). The domain layer only
declares the shape; the deepagents-based orchestrator is infra_engineer's file.
"""

from typing import Protocol

from domain.entities.agent_finding import AgentInput, ReviewResult


class ReviewOrchestratorPort(Protocol):
    async def run_review(self, review_input: AgentInput, agent_names: list[str]) -> ReviewResult:
        """Run the configured agents for this request and return the aggregated result.

        Args:
            review_input: Domain input; ``repo_root`` carries the DB-resolved local_path.
            agent_names: Routing-policy agent list for this request_type. Empty list is
                valid (orchestrator answers directly, e.g. explain_question).

        Returns:
            A ReviewResult: ``aggregated`` is the aggregator's synthesized AgentOutput
            (agent_name="aggregator"); ``per_agent`` carries one AgentOutput per routed
            subagent for the audit trail.
        """
        ...
