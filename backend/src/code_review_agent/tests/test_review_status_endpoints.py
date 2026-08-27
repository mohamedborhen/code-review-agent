"""Tests for review status endpoints — GET /reviews/running, GET /reviews/latest,
and GET /reviews/{session_id}.

The DB-operation behavior of the former private helpers now lives in
ReviewSessionRepository and is tested in test_review_session_repository.py.
This module keeps only the route-registration checks.
"""

import unittest

from infrastructure.api.routes.review import router


class RouteRegistrationTest(unittest.TestCase):
    def test_reviews_running_route_exists(self):
        """GET /reviews/running route is registered."""
        from infrastructure.api.routes.review import router
        routes = {r.path: r.methods for r in router.routes}
        self.assertIn("/reviews/running", routes)
        self.assertIn("GET", routes["/reviews/running"])

    def test_reviews_latest_route_exists(self):
        """GET /reviews/latest route is registered."""
        from infrastructure.api.routes.review import router
        routes = {r.path: r.methods for r in router.routes}
        self.assertIn("/reviews/latest", routes)
        self.assertIn("GET", routes["/reviews/latest"])

    def test_reviews_by_id_route_exists(self):
        """GET /reviews/{session_id} route is registered."""
        from infrastructure.api.routes.review import router
        routes = {r.path: r.methods for r in router.routes}
        self.assertIn("/reviews/{session_id}", routes)
        self.assertIn("GET", routes["/reviews/{session_id}"])

    def test_reviews_running_declared_before_by_id(self):
        """FastAPI first-match-wins: /reviews/running must be before /reviews/{session_id}."""
        from infrastructure.api.routes.review import router
        route_paths = [r.path for r in router.routes if hasattr(r, "path")]
        running_idx = route_paths.index("/reviews/running")
        by_id_idx = route_paths.index("/reviews/{session_id}")
        self.assertLess(running_idx, by_id_idx)

    def test_reviews_latest_declared_before_by_id(self):
        """FastAPI first-match-wins: /reviews/latest must be before /reviews/{session_id}."""
        from infrastructure.api.routes.review import router
        route_paths = [r.path for r in router.routes if hasattr(r, "path")]
        latest_idx = route_paths.index("/reviews/latest")
        by_id_idx = route_paths.index("/reviews/{session_id}")
        self.assertLess(latest_idx, by_id_idx)
