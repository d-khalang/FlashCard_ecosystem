"""
Unit tests for health and readiness endpoints.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pymongo.errors import ConnectionFailure

from flashcard.api.routes.health import health_check, readiness_check


class _DummyRequest:
    def __init__(self, *, ping_side_effect=None):
        admin = MagicMock()
        admin.command = AsyncMock(side_effect=ping_side_effect)
        client = MagicMock()
        client.admin = admin
        self.app = SimpleNamespace(state=SimpleNamespace(mongo_client=client))


class TestHealthCheck:

    async def test_returns_200_for_liveness(self):
        request = _DummyRequest()

        response = await health_check(request)

        assert response == {"status": "ok"}
        request.app.state.mongo_client.admin.command.assert_not_awaited()

class TestReadinessCheck:

    async def test_returns_200_when_db_is_healthy(self):
        request = _DummyRequest()

        response = await readiness_check(request)

        assert response == {"status": "ready"}
        request.app.state.mongo_client.admin.command.assert_awaited_once_with("ping")

    async def test_returns_503_when_db_is_unreachable(self):
        request = _DummyRequest(ping_side_effect=ConnectionFailure("timed out"))

        response = await readiness_check(request)

        assert response.status_code == 503
        body = response.body
        assert b"unhealthy" in body
        assert b"database unreachable" in body

    async def test_returns_503_on_unexpected_db_error(self):
        request = _DummyRequest(ping_side_effect=RuntimeError("something else"))

        response = await readiness_check(request)

        assert response.status_code == 503
