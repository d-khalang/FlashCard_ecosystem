"""
The client of our conjugator (it-conjugator-api, v2 routes; docs/verbs/contract.md section 3).

The conjugator is our own offline service, so nothing is cached here: every lookup asks it.
"""
import re
from dataclasses import dataclass
from typing import Optional, Union

from flashcard.schemas.verbs import Conjugation, Infinitives, Suggestions, VerbNotFound
from flashcard.utils.logger import get_logger
from flashcard.utils.tracing import observe

logger = get_logger(__name__)

# Query limits shared by the bot and the Mini App (contract section 2, "Match").
MAX_QUERY_CHARS = 60
MAX_QUERY_WORDS = 4
# Words per POST /v2/infinitives.
INFINITIVES_BATCH = 500
SUGGEST_LIMIT = 8


class ConjugatorError(Exception):
    """The conjugator could not be reached or gave an answer outside the contract."""


@dataclass(frozen=True)
class ScraperConfig:
    url: str
    port: int
    api_key: str

    @classmethod
    def from_settings(cls, settings) -> Optional["ScraperConfig"]:
        """None when incomplete (Settings requires all three when conjugation is on)."""
        if not settings.SCRAPER_URL or settings.SCRAPER_PORT is None or not settings.SCRAPER_API_KEY:
            return None
        return cls(url=settings.SCRAPER_URL, port=settings.SCRAPER_PORT, api_key=settings.SCRAPER_API_KEY)


class VerbService:
    # Up to four words of letters and apostrophes, single spaces between them
    # ("vado", "sono andato", "me ne vado", "l'ho fatto").
    _WORD = r"[A-Za-zÀ-ÖØ-öø-ÿ']+"
    REGEX_VERB = rf"^{_WORD}(?: {_WORD}){{0,{MAX_QUERY_WORDS - 1}}}$"

    def __init__(self, http_client=None, scraper: Optional[ScraperConfig] = None):
        """`scraper`: where the conjugator listens and its key."""
        self.http_client = http_client
        self.scraper = scraper

    @staticmethod
    def normalize(query: str) -> str:
        """Trim, collapse whitespace, lowercase, and use the plain apostrophe."""
        return " ".join(query.replace("’", "'").split()).lower()

    def is_valid_verb(self, query: str) -> bool:
        """
        Format only, for a normalized query. Callers pass the query itself: command
        parsing (e.g. "/verb ...") belongs to the Telegram handler.
        """
        if not isinstance(query, str) or not query or len(query) > MAX_QUERY_CHARS:
            return False
        return re.match(self.REGEX_VERB, query) is not None

    def _config(self) -> ScraperConfig:
        if self.scraper is None:
            raise RuntimeError("Conjugation service is enabled but its settings are incomplete")
        return self.scraper

    def _url(self, path: str) -> str:
        return f"{self._config().url}:{self._config().port}{path}"

    def _headers(self) -> dict:
        return {"X-API-Key": self._config().api_key}

    @observe(name="VerbService.conjugate")
    async def conjugate(self, query: str) -> Union[Conjugation, VerbNotFound]:
        """The verb a query (infinitive or any form) belongs to, or why there is none."""
        url = self._url("/v2/conjugate")
        try:
            res = await self.http_client.get(url, params={"q": query}, headers=self._headers())
        except Exception as e:
            raise ConjugatorError(f"conjugate request failed: {type(e).__name__}") from e
        if res.status_code == 404:
            return self._read(VerbNotFound, res, "conjugate")
        if res.status_code != 200:
            raise ConjugatorError(f"conjugate answered {res.status_code}")
        return self._read(Conjugation, res, "conjugate")

    async def suggest(self, prefix: str, limit: int = SUGGEST_LIMIT) -> list[str]:
        """Infinitives starting with `prefix`, most common first."""
        url = self._url("/v2/suggest")
        try:
            res = await self.http_client.get(url, params={"q": prefix, "limit": limit}, headers=self._headers())
        except Exception as e:
            raise ConjugatorError(f"suggest request failed: {type(e).__name__}") from e
        if res.status_code != 200:
            raise ConjugatorError(f"suggest answered {res.status_code}")
        return self._read(Suggestions, res, "suggest").items

    async def infinitives(self, words: list[str]) -> dict[str, Optional[str]]:
        """word -> its infinitive when the word is one (andare, svegliarsi), else None."""
        url = self._url("/v2/infinitives")
        found: dict[str, Optional[str]] = {}
        for start in range(0, len(words), INFINITIVES_BATCH):
            batch = words[start:start + INFINITIVES_BATCH]
            try:
                res = await self.http_client.post(url, json={"words": batch}, headers=self._headers())
            except Exception as e:
                raise ConjugatorError(f"infinitives request failed: {type(e).__name__}") from e
            if res.status_code != 200:
                raise ConjugatorError(f"infinitives answered {res.status_code}")
            found.update(self._read(Infinitives, res, "infinitives").infinitives)
        return found

    @staticmethod
    def _read(model, res, route: str):
        try:
            return model.model_validate(res.json())
        except Exception as e:  # invalid JSON or a shape outside the contract
            raise ConjugatorError(f"{route} answer outside the contract: {type(e).__name__}") from e
