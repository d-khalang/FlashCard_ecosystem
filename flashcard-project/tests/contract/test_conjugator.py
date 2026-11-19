"""The bot's VerbService reads what the real it-conjugator v2 API answers (started here from its source)."""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time

import httpx
import pytest

from flashcard.schemas.verbs import TENSE_IDS, Conjugation, VerbNotFound
from flashcard.services.verb import ConjugatorError, ScraperConfig, VerbService
from tests.verb_fixtures import load

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


def _service(client, conjugator, *, key: str | None = None) -> VerbService:
    url, port, right_key = conjugator
    return VerbService(http_client=client, scraper=ScraperConfig(url=url, port=port, api_key=key or right_key))


async def _conjugate(conjugator, query: str):
    async with httpx.AsyncClient(timeout=10) as client:
        return await _service(client, conjugator).conjugate(query)


def _primary(answer, tense_id: str, person: str) -> str:
    slot = next(s for s in answer.verb.tense(tense_id).slots if s.person == person)
    return slot.primary.text


async def test_a_verb_comes_back_in_the_v2_shape(conjugator):
    answer = await _conjugate(conjugator, "andare")

    assert isinstance(answer, Conjugation) and answer.verb.infinitive == "andare"
    assert [t.id for t in answer.verb.tenses] == [t for t in TENSE_IDS if answer.verb.tense(t)]
    present = answer.verb.tense("indicativo-presente")
    assert [s.person for s in present.slots] == ["1s", "2s", "3s", "1p", "2p", "3p"]


# Regression: the conjugator's data used to give dialect or archaic forms for these (andare: vò/và,
# fare: fazzo/face, essere: sò/ene), fixed in it-conjugator-api's build_db.py.
@pytest.mark.parametrize("verb, io, lui", [("andare", "vado", "va"), ("fare", "faccio", "fa"),
                                          ("essere", "sono", "è"), ("dare", "do", "dà"),
                                          ("stare", "sto", "sta")])
async def test_irregular_verbs_have_their_standard_forms(conjugator, verb, io, lui):
    answer = await _conjugate(conjugator, verb)

    assert (_primary(answer, "indicativo-presente", "1s"), _primary(answer, "indicativo-presente", "3s")) == (io, lui)


@pytest.mark.parametrize("query, infinitive", [("vado", "andare"), ("sono andato", "andare")])
async def test_forms_and_queries_with_spaces_find_their_verb(conjugator, query, infinitive):
    answer = await _conjugate(conjugator, query)

    assert isinstance(answer, Conjugation) and answer.verb.infinitive == infinitive


async def test_an_unknown_word_is_not_found(conjugator):
    assert isinstance(await _conjugate(conjugator, "qwertyuiop"), VerbNotFound)


async def test_suggest_and_infinitives(conjugator):
    async with httpx.AsyncClient(timeout=10) as client:
        service = _service(client, conjugator)
        suggestions = await service.suggest("and")
        infinitives = await service.infinitives(["prendere", "letto", "svegliarsi", "andare d'accordo"])

    assert "andare" in suggestions
    assert infinitives == load("conjugator/infinitives-response.json")["infinitives"]


async def test_a_wrong_key_is_refused(conjugator):
    async with httpx.AsyncClient(timeout=10) as client:
        with pytest.raises(ConjugatorError):
            await _service(client, conjugator, key="wrong").conjugate("andare")
