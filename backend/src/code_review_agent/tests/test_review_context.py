"""Unit tests for the review pre-flight use-case and run_review routing.

Covers the three error outcomes (unknown repo_id -> RepoNotFoundError, graph
not ready -> GraphNotReadyError, unknown request_type -> UnknownRequestTypeError)
using fake ports — no DB, no FastAPI.
"""

import asyncio
import unittest

from application.review_service.errors import (
    GraphNotReadyError,
    RepoNotFoundError,
    UnknownRequestTypeError,
)
from application.review_service.prepare_review_context import PrepareReviewContextService
from application.review_service.run_review import run_review
from domain.entities.agent_finding import AgentInput, AgentOutput, ReviewResult
from domain.entities.repo_workspace import RepoWorkspace


class _FakeWorkspaceQuery:
    def __init__(self, workspace: RepoWorkspace | None) -> None:
        self._workspace = workspace

    def get_by_repo_id(self, repo_id: str) -> RepoWorkspace | None:
        self.last_repo_id = repo_id
        return self._workspace


class _FakeReadiness:
    def __init__(self, ready: bool = True) -> None:
        self._ready = ready
        self.last = None

    def is_ready(self, repo_id: str, commit_hash: str) -> bool:
        self.last = (repo_id, commit_hash)
        return self._ready


class PrepareReviewContextServiceTest(unittest.TestCase):
    def test_returns_local_path(self):
        service = PrepareReviewContextService(
            _FakeWorkspaceQuery(RepoWorkspace(repo_id="acme/app", local_path="/ws/acme_app")),
            _FakeReadiness(ready=True),
        )
        self.assertEqual(service.execute("acme/app", "abc123"), "/ws/acme_app")

    def test_unknown_repo_raises_repo_not_found(self):
        service = PrepareReviewContextService(
            _FakeWorkspaceQuery(None),
            _FakeReadiness(ready=True),
        )
        with self.assertRaises(RepoNotFoundError):
            service.execute("ghost/app", "abc123")

    def test_unready_graph_raises_graph_not_ready(self):
        service = PrepareReviewContextService(
            _FakeWorkspaceQuery(RepoWorkspace(repo_id="acme/app", local_path="/ws/acme_app")),
            _FakeReadiness(ready=False),
        )
        with self.assertRaises(GraphNotReadyError):
            service.execute("acme/app", "abc123")


class RunReviewTest(unittest.TestCase):
    class _FakeOrchestrator:
        def __init__(self) -> None:
            self.received = None

        async def run_review(self, review_input, agent_names) -> ReviewResult:
            self.received = (review_input, agent_names)
            return ReviewResult(aggregated=AgentOutput(agent_name="aggregator"))

    def test_unknown_request_type_raises(self):
        async def run():
            with self.assertRaises(UnknownRequestTypeError):
                await run_review(
                    AgentInput(repo_id="acme/app", graph_commit_hash="abc123", request_type="nope"),
                    self._FakeOrchestrator(),
                )

        asyncio.run(run())

    def test_delegates_known_request_type(self):
        async def run():
            orchestrator = self._FakeOrchestrator()
            result = await run_review(
                AgentInput(repo_id="acme/app", graph_commit_hash="abc123", request_type="security_question"),
                orchestrator,
            )
            self.assertEqual(result.aggregated.agent_name, "aggregator")
            self.assertEqual(orchestrator.received[1], ["security"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
