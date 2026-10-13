"""
Verb use cases: look up a verb's conjugation (cached in our DB, else our scraper).

Lookups are counted but not limited: they cost no paid provider calls.
Callers own presentation and error reporting; lookup errors propagate.
"""
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Union

from flashcard.app.types import UserId
from flashcard.schemas.conjugations import ConjugationResponse
from flashcard.services.consumption import ConsumptionService
from flashcard.services.verb import VerbService

# Awaited with the cleaned verb once input is valid, before the lookup.
SearchingNotifier = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class Found:
    data: ConjugationResponse


@dataclass(frozen=True)
class NoVerb:
    pass


@dataclass(frozen=True)
class InvalidVerb:
    verb: str


@dataclass(frozen=True)
class NotFound:
    verb: str


LookupResult = Union[Found, NoVerb, InvalidVerb, NotFound]


class VerbUseCases:
    def __init__(self, verb_service: VerbService, consumption_service: ConsumptionService):
        self.verbs = verb_service
        self.consumption = consumption_service

    async def lookup(self, user_id: UserId, text: Optional[str],
                     on_searching: Optional[SearchingNotifier] = None) -> LookupResult:
        verb = (text or "").strip()
        if not verb:
            return NoVerb()
        if not self.verbs.is_valid_verb(verb):
            return InvalidVerb(verb=verb)

        if on_searching is not None:
            await on_searching(verb)
        data = await self.verbs.get_verb_data(verb)
        if not data:
            return NotFound(verb=verb)

        await self.consumption.increment(user_id, "verb_lookups")
        return Found(data=data)

    async def conjugation(self, verb: str) -> Union[Found, NotFound]:
        """Conjugation data for navigating an already shown verb; not counted."""
        data = await self.verbs.get_verb_data(verb)
        return Found(data=data) if data else NotFound(verb=verb)
