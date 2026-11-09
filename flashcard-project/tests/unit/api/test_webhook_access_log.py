"""The webhook's path token and secret never reach the logs (real uvicorn, real access log)."""
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import uvicorn

from flashcard.api.main import create_app
from flashcard.settings import Settings
from flashcard.utils.logger import ACCESS_LOGGER_NAME, MASKED_PATH, mask_access_log_path

PATH_TOKEN = "path-token-must-not-be-logged"
WEBHOOK_PATH = f"/webhook/telegram/{PATH_TOKEN}"
SECRET = "header-secret-must-not-be-logged"


@pytest.fixture
def clean_uvicorn_logging():
    """uvicorn configures process-wide loggers, bound to pytest's temporary stdout."""
    yield
    for name in ("uvicorn", "uvicorn.error", ACCESS_LOGGER_NAME):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.filters.clear()


def _build_app():
    settings = Settings(_env_file=None, WEBHOOK_PATH=WEBHOOK_PATH, WEBHOOK_SECRET=SECRET)
    app = create_app(settings)
    # No lifespan here: the route only needs what `running_bot` would have put on the state.
    app.state.telegram = SimpleNamespace(
        bot=MagicMock(),
        dispatcher=SimpleNamespace(feed_update=AsyncMock(return_value=None)),
        handler_data={},
        logger_bot=MagicMock(),
        admin_id=1,
    )
    return app


@pytest.mark.parametrize("http_impl", ["h11", "httptools"])
async def test_webhook_path_and_secret_are_not_in_the_access_log(
    http_impl, capsys, clean_uvicorn_logging,
):
    pytest.importorskip(http_impl)
    # A factory, as in production: uvicorn configures its logging before the app adds the mask.
    server = uvicorn.Server(uvicorn.Config(
        _build_app, factory=True, host="127.0.0.1", port=0, lifespan="off", http=http_impl, log_level="info",
    ))
    serving = asyncio.create_task(server.serve())
    try:
        while not server.started and not serving.done():
            await asyncio.sleep(0.01)
        assert server.started, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        secret_header = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            accepted = await client.post(WEBHOOK_PATH, json={"update_id": 1}, headers=secret_header)
            with_query = await client.post(f"{WEBHOOK_PATH}?x=1", json={"update_id": 2}, headers=secret_header)
            forged = await client.post(WEBHOOK_PATH, json={"update_id": 3})
            health = await client.get("/health")
    finally:
        server.should_exit = True
        await serving

    assert (accepted.status_code, with_query.status_code, forged.status_code) == (200, 200, 403)
    assert health.status_code == 200

    captured = capsys.readouterr()
    logs = captured.out + captured.err
    assert PATH_TOKEN not in logs
    assert SECRET not in logs
    # The requests are still logged, so the absence above proves something.
    assert f'POST {MASKED_PATH} HTTP/1.1" 200' in logs
    assert f'POST {MASKED_PATH} HTTP/1.1" 403' in logs
    assert 'GET /health HTTP/1.1" 200' in logs


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        ACCESS_LOGGER_NAME, logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("10.0.0.1:5000", "POST", path, "1.1", 200), None,
    )


class TestMaskAccessLogPath:

    @pytest.mark.parametrize("logged, expected", [
        ("/webhook/telegram/token", MASKED_PATH),
        ("/webhook/telegram/token/", MASKED_PATH),
        ("/webhook/telegram/token?x=1", MASKED_PATH),
        ("/webhook/telegram", "/webhook/telegram"),
        ("/webhook/telegram/token-2", "/webhook/telegram/token-2"),
        ("/health", "/health"),
    ])
    def test_only_the_webhook_path_is_masked(self, logged, expected, clean_uvicorn_logging):
        mask_access_log_path("/webhook/telegram/token")
        record = _access_record(logged)

        assert logging.getLogger(ACCESS_LOGGER_NAME).filter(record)
        assert record.args == ("10.0.0.1:5000", "POST", expected, "1.1", 200)

    def test_a_percent_encoded_path_is_masked(self, clean_uvicorn_logging):
        mask_access_log_path("/webhook/telegram/to=ken")
        record = _access_record("/webhook/telegram/to%3Dken")

        logging.getLogger(ACCESS_LOGGER_NAME).filter(record)

        assert record.args[2] == MASKED_PATH

    def test_a_later_call_replaces_the_earlier_mask(self, clean_uvicorn_logging):
        mask_access_log_path("/old")
        mask_access_log_path("/new")

        assert len(logging.getLogger(ACCESS_LOGGER_NAME).filters) == 1
