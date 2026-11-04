"""
The Mini App HTTP app without a database: sign-in errors, headers, static files, error shape.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import ASGITransport

from flashcard.app.study import CurrentState
from flashcard.miniapp.api import create_app
from flashcard.miniapp.rate_limit import RateLimiter
from flashcard.settings import get_setting
from tests.integration.study_helpers import auth_header, sign_init_data


def _app(**settings):
    app = create_app(get_setting().model_copy(update=settings))
    users = SimpleNamespace(record_seen=AsyncMock())
    study = SimpleNamespace(current=AsyncMock(return_value=CurrentState(card=None, undo_available=False)))
    app.state.core = SimpleNamespace(user_service=users, study_use_cases=study)
    return app


def _client(app):
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _get(app, path, **kwargs):
    async with _client(app) as client:
        return await client.get(path, **kwargs)


def _error(response):
    return response.status_code, response.json()["error"]["code"]


class TestSignIn:

    async def test_no_header_is_auth_required(self):
        assert _error(await _get(_app(), "/api/v1/study/current")) == (401, "auth_required")

    @pytest.mark.parametrize("header", ["", "tma", "tma ", "Bearer abc", "tma garbage"])
    async def test_a_bad_header_is_auth_required(self, header):
        response = await _get(_app(), "/api/v1/study/current", headers={"Authorization": header})

        assert _error(response) == (401, "auth_required")

    async def test_a_signature_from_another_bot_is_refused(self):
        response = await _get(_app(), "/api/v1/study/current", headers=auth_header(42, bot_token="9:other"))

        assert _error(response) == (401, "auth_required")

    async def test_old_init_data_is_refused(self):
        response = await _get(_app(), "/api/v1/study/current", headers=auth_header(42, auth_age_seconds=90000))

        assert _error(response) == (401, "auth_required")

    async def test_a_signed_user_is_let_in_and_recorded_as_seen(self):
        app = _app()

        response = await _get(app, "/api/v1/study/current", headers=auth_header(42, username="noor"))

        assert response.status_code == 200 and response.json() == {"card": None, "undo_available": False}
        app.state.core.user_service.record_seen.assert_awaited_once_with(42, "noor")

    async def test_the_error_does_not_echo_the_init_data(self):
        header = auth_header(42, bot_token="9:other")

        response = await _get(_app(), "/api/v1/study/current", headers=header)

        assert header["Authorization"].split(" ")[1] not in response.text

    async def test_users_outside_the_allowed_list_get_403_and_are_not_recorded(self):
        app = _app(MINIAPP_ALLOWED_USER_IDS="7, 8")

        refused = await _get(app, "/api/v1/study/current", headers=auth_header(42))
        allowed = await _get(app, "/api/v1/study/current", headers=auth_header(8))

        assert _error(refused) == (403, "not_allowed")
        assert allowed.status_code == 200
        app.state.core.user_service.record_seen.assert_awaited_once()

    async def test_without_an_allowed_list_everyone_may_use_it(self):
        assert (await _get(_app(MINIAPP_ALLOWED_USER_IDS=None), "/api/v1/study/current",
                           headers=auth_header(99))).status_code == 200


class TestRateLimit:

    async def test_over_the_limit_is_429_with_retry_after(self):
        app = _app()
        app.state.limiters["general"] = RateLimiter(2)

        async with _client(app) as client:
            statuses = [(await client.get("/api/v1/study/current", headers=auth_header(42))).status_code
                        for _ in range(2)]
            refused = await client.get("/api/v1/study/current", headers=auth_header(42))
            other_user = await client.get("/api/v1/study/current", headers=auth_header(43))

        assert statuses == [200, 200]
        assert _error(refused) == (429, "rate_limited")
        assert 1 <= int(refused.headers["Retry-After"]) <= 60
        assert other_user.status_code == 200

    async def test_the_llm_routes_have_their_own_smaller_budget(self):
        app = _app()
        limiters = app.state.limiters

        assert (limiters["llm"].limit, limiters["general"].limit) == (20, 120)


class TestHeadersAndErrors:

    async def test_health_needs_no_sign_in(self):
        response = await _get(_app(), "/health")

        assert response.status_code == 200 and response.json() == {"status": "ok"}

    async def test_every_response_has_the_csp_and_nosniff(self):
        app = _app()

        for path in ("/health", "/api/v1/study/current", "/api/v1/nope"):
            response = await _get(app, path)
            policy = response.headers["Content-Security-Policy"]
            assert "frame-ancestors https://web.telegram.org https://*.telegram.org" in policy, path
            assert "script-src 'self' https://telegram.org" in policy, path
            assert response.headers["X-Content-Type-Options"] == "nosniff", path

    async def test_api_responses_are_not_cached(self):
        response = await _get(_app(), "/api/v1/study/current", headers=auth_header(42))

        assert response.headers["Cache-Control"] == "no-store"

    async def test_an_unknown_route_is_the_json_404(self):
        response = await _get(_app(), "/api/v1/nope")

        assert _error(response) == (404, "not_found")

    async def test_a_bad_body_is_422_and_does_not_echo_values(self):
        async with _client(_app()) as client:
            response = await client.post("/api/v1/study/grade", headers=auth_header(42),
                                         json={"delivery_id": -1, "expression_id": "SECRET-VALUE", "direction": "forward",
                                               "grade": 9})

        assert _error(response) == (422, "invalid_request")
        assert "SECRET-VALUE" not in response.text

    async def test_the_sign_in_is_checked_before_the_body(self):
        async with _client(_app()) as client:
            response = await client.post("/api/v1/study/grade", json={"grade": "x"})

        assert _error(response) == (401, "auth_required")

    async def test_there_are_no_interactive_docs(self):
        app = _app()

        for path in ("/docs", "/openapi.json", "/redoc"):
            assert (await _get(app, path)).status_code == 404


class TestStaticFiles:

    @pytest.fixture
    def app(self, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "index.html").write_text("<html>app</html>")
        (tmp_path / "assets" / "app-123.js").write_text("console.log(1)")
        return _app(MINIAPP_STATIC_DIR=str(tmp_path))

    async def test_index_is_served_and_never_cached(self, app):
        response = await _get(app, "/")

        assert response.status_code == 200 and "app" in response.text
        assert response.headers["Cache-Control"] == "no-cache"
        assert "frame-ancestors" in response.headers["Content-Security-Policy"]

    async def test_fingerprinted_assets_are_cached_for_good(self, app):
        response = await _get(app, "/assets/app-123.js")

        assert response.status_code == 200
        assert "immutable" in response.headers["Cache-Control"]
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    async def test_an_app_route_falls_back_to_index_but_a_missing_file_does_not(self, app):
        route = await _get(app, "/collection")
        missing = await _get(app, "/assets/missing.js")

        assert route.status_code == 200 and "app" in route.text
        assert missing.status_code == 404

    async def test_the_files_never_shadow_the_api(self, app):
        unknown = await _get(app, "/api/v1/nope")
        posting = None
        async with _client(app) as client:
            posting = await client.post("/api/v1/nope")
        signed_in = await _get(app, "/api/v1/study/current", headers=auth_header(42))
        health = await _get(app, "/health")

        assert _error(unknown) == (404, "not_found")
        assert _error(posting) == (404, "not_found")
        assert signed_in.json() == {"card": None, "undo_available": False}
        assert health.json() == {"status": "ok"}

    async def test_a_missing_directory_fails_at_startup(self, tmp_path):
        with pytest.raises(RuntimeError):
            _app(MINIAPP_STATIC_DIR=str(tmp_path / "missing"))


def test_signing_helper_makes_distinct_data():
    assert sign_init_data(1) != sign_init_data(2)
