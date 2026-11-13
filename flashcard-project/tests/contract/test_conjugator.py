"""The bot's VerbService reads what the real it-conjugator API answers (started here from its source)."""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time

import httpx
import pytest

from flashcard.services.verb import ScraperConfig, VerbService

from .conftest import CONJUGATOR_DIR, missing


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def conjugator():
    """(url, port, api key) of the conjugator API running from the submodule, the Dockerfile's command."""
    if not (CONJUGATOR_DIR / "verbs.db").is_file():
        missing(f"no conjugator at {CONJUGATOR_DIR} (git submodule update --init it-conjugator-api)")
    port, key = _free_port(), secrets.token_hex(16)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=CONJUGATOR_DIR, env={**os.environ, "SCRAPER_API_KEY": key},
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(f"the conjugator stopped: {process.stderr.read().decode(errors='replace')[-2000:]}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("the conjugator did not start within 60 s")
        yield "http://127.0.0.1", port, key
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


async def _lookup(conjugator, verb: str, *, key: str | None = None):
    url, port, right_key = conjugator
    async with httpx.AsyncClient(timeout=10) as client:
        service = VerbService(conjugations=None, http_client=client,
                              scraper=ScraperConfig(url=url, port=port, api_key=key or right_key))
        return await service.get_verb_from_api(verb)


async def test_a_verb_comes_back_in_the_shape_the_bot_reads(conjugator):
    data = await _lookup(conjugator, "andare")

    assert data is not None and data.auxiliary
    present = data.conjugations["indicativo"]["presente"]
    assert len(present) == 6 and all(form.strip() for form in present.values())


# Known bug in the conjugator's data (2026-11-13, production included): common irregular verbs get
# dialect or archaic forms (andare: vò/và, fare: fazzo/face, essere: sò/ene). strict: when the data is
# fixed this starts passing and fails as XPASS, so the mark gets removed.
@pytest.mark.xfail(strict=True, reason="conjugator data gives dialect forms for irregular verbs")
@pytest.mark.parametrize("verb, io, lui", [("andare", "vado", "va"), ("fare", "faccio", "fa"),
                                          ("essere", "sono", "è")])
async def test_irregular_verbs_have_their_standard_forms(conjugator, verb, io, lui):
    present = (await _lookup(conjugator, verb)).conjugations["indicativo"]["presente"]

    assert (present["io"], present["lui, lei, Lei, egli"]) == (io, lui)


async def test_a_pronominal_verb_is_conjugated(conjugator):
    data = await _lookup(conjugator, "arrabbiarsi")

    assert data is not None
    assert "arrabbio" in data.conjugations["indicativo"]["presente"]["io"]


async def test_a_wrong_key_is_refused(conjugator):
    assert await _lookup(conjugator, "andare", key="wrong") is None
