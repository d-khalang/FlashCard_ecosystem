"""
The built Mini App in real browser engines on phone-sized screens, against the real API.

The API serves miniapp/dist (a production build, `npm run build`) on a random 127.0.0.1 port, with
the integration harness behind it: one test MongoDB, a recording fake Telegram, fake LLM and speech.
Telegram's own script is replaced by a stub that hands the app signed test init data; every other
request that leaves 127.0.0.1 is blocked and fails the test.

Locally the tests skip when the build or the browsers are missing; with KARTINO_REQUIRE_BROWSER=1
(CI) they fail instead. On a failure, a screenshot and a Playwright trace go to tests/browser/.artifacts.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest
import uvicorn

from tests.integration.conftest import (  # noqa: F401  (fixtures)
    fake_http_client, mongo_cols, open_harness, study_llm, trace_logger,
)
from tests.integration.harness import USER
from tests.integration.study_helpers import sign_init_data

DIST = Path(__file__).resolve().parents[3] / "miniapp" / "dist"
ARTIFACTS = Path(__file__).resolve().parent / ".artifacts"
TELEGRAM_SCRIPT = "https://telegram.org/js/telegram-web-app.js"
HINTS_STORAGE_KEY = "kartino.study-hints.v1"
ALL_HINTS = ["reveal", "grades", "refresh"]
# (Playwright device, browser engine): an iPhone on WebKit, an Android phone on Chromium.
DEVICES = [("iPhone 14", "webkit"), ("Pixel 7", "chromium")]


def _missing(reason: str):
    if os.environ.get("KARTINO_REQUIRE_BROWSER") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    report = yield
    setattr(item, f"rep_{report.when}", report)
    return report


def telegram_stub(init_data: str, language: str = "en") -> str:
    """window.Telegram.WebApp as the app uses it: signed init data, the rest harmless no-ops."""
    return f"""
    (() => {{
      const noop = () => {{}};
      window.Telegram = {{ WebApp: {{
        initData: {json.dumps(init_data)},
        initDataUnsafe: {{ user: {{ id: {USER}, language_code: {json.dumps(language)} }} }},
        version: '8.0', platform: 'ios', colorScheme: 'light', themeParams: {{}},
        isVersionAtLeast: () => true,
        ready: noop, expand: noop, close: noop, disableVerticalSwipes: noop,
        setHeaderColor: noop, setBackgroundColor: noop, setBottomBarColor: noop, onEvent: noop, offEvent: noop,
        safeAreaInset: {{ top: 0, bottom: 0, left: 0, right: 0 }},
        contentSafeAreaInset: {{ top: 0, bottom: 0, left: 0, right: 0 }},
        BackButton: {{ show: noop, hide: noop, onClick: noop, offClick: noop }},
        HapticFeedback: {{ impactOccurred: noop, notificationOccurred: noop, selectionChanged: noop }},
      }} }};
    }})();
    """


@pytest.fixture
async def live(monkeypatch, mongo_cols, study_llm, fake_http_client, trace_logger):
    """(harness, base URL): the API serving the built Mini App on a random local port."""
    if not (DIST / "index.html").is_file():
        _missing(f"no Mini App build at {DIST} (run `npm run build` in miniapp/)")
    async with open_harness(monkeypatch, mongo_cols, study_llm, fake_http_client, static_dir=str(DIST)) as harness:
        server = uvicorn.Server(uvicorn.Config(harness.app, host="127.0.0.1", port=0, log_level="warning",
                                               lifespan="off", ws="none",
                                               timeout_graceful_shutdown=1))
        task = asyncio.create_task(server.serve())
        while not server.started:
            if task.done():
                task.result()  # raises what stopped it
            await asyncio.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        try:
            yield harness, f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            await task


@pytest.fixture(params=DEVICES, ids=[engine for _, engine in DEVICES])
async def browser_context(request):
    from playwright.async_api import Error, async_playwright

    device, engine = request.param
    async with async_playwright() as playwright:
        try:
            browser = await getattr(playwright, engine).launch()
        except Error as error:
            first = str(error).splitlines()[0]
            _missing(f"{engine} is not installed ({first}); run `python -m playwright install {engine}`")
        context = await browser.new_context(**playwright.devices[device])
        try:
            yield context
        finally:
            await context.close()
            await browser.close()


@pytest.fixture
def hints_seen() -> list[str]:
    """The one-time study hints already seen; all by default, so they do not cover the flows under test."""
    return list(ALL_HINTS)


@pytest.fixture
async def page(request, live, browser_context, hints_seen):
    """A page on the live Mini App as the test user, offline except for 127.0.0.1."""
    harness, base_url = live
    context = browser_context
    outside: list[str] = []

    async def route(route):
        url = route.request.url
        if url.startswith(TELEGRAM_SCRIPT):
            await route.fulfill(content_type="text/javascript", body=telegram_stub(sign_init_data(USER)))
        elif re.match(r"^(http|ws)s?://127\.0\.0\.1[:/]", url) or url.startswith(("data:", "blob:")):
            await route.continue_()
        else:
            outside.append(url)
            await route.abort()

    await context.route("**/*", route)
    await context.add_init_script(f"localStorage.setItem({json.dumps(HINTS_STORAGE_KEY)}, "
                                  f"{json.dumps(json.dumps(hints_seen))})")
    await context.tracing.start(screenshots=True, snapshots=True)
    page = await context.new_page()
    page.base_url = base_url
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        yield page
    finally:
        # The checks below fail a test whose body passed, so they count as a failure here too.
        call = getattr(request.node, "rep_call", None)
        failed = call is None or call.failed or bool(outside) or bool(errors)
        if failed:
            ARTIFACTS.mkdir(exist_ok=True)
            name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
            await page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)
            await context.tracing.stop(path=str(ARTIFACTS / f"{name}.zip"))
        else:
            await context.tracing.stop()
        # Closes the page's keep-alive connections, so the server stops at once whatever the fixture order.
        await page.close()
    assert not outside, f"requests left 127.0.0.1: {outside}"
    assert not errors, f"uncaught errors in the page: {errors}"
