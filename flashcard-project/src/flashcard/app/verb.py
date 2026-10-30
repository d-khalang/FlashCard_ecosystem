"""
Verb use cases: look up a verb's conjugation (cached in our DB, else our scraper).

Lookups are counted but not limited: they cost no paid provider calls.
Callers parse first, then look up; they own presentation and error reporting,
and lookup errors propagate.
"""
from dataclasses import dataclass
from typing import Optional, Union

from flashcard.schemas.user import UserId
from flashcard.schemas.conjugations import ConjugationResponse
from flashcard.services.consumption import ConsumptionService
from flashcard.services.verb import VerbService


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


ParseResult = Union[str, NoVerb, InvalidVerb]
LookupResult = Union[Found, NotFound]


class VerbUseCases:
    def __init__(self, verb_service: VerbService, consumption_service: ConsumptionService):
        self.verbs = verb_service
        self.consumption = consumption_service

    def parse(self, text: Optional[str]) -> ParseResult:
        """The cleaned verb, or why the input is not one."""
        verb = (text or "").strip()
        if not verb:
            return NoVerb()
        if not self.verbs.is_valid_verb(verb):
            return InvalidVerb(verb=verb)
        return verb

    async def lookup(self, user_id: UserId, verb: str) -> LookupResult:
        """Look up a verb returned by `parse`; raises ValueError for anything else."""
        if self.parse(verb) != verb:
            raise ValueError(f"Not a parsed verb: {verb!r}")
        data = await self.verbs.get_verb_data(verb)
        if not data:
            return NotFound(verb=verb)

        await self.consumption.increment(user_id, "verb_lookups")
        return Found(data=data)

    async def conjugation(self, verb: str) -> LookupResult:
        """Conjugation data for navigating an already shown verb; not counted."""
        data = await self.verbs.get_verb_data(verb)
        return Found(data=data) if data else NotFound(verb=verb)
