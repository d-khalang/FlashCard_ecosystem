"""
Verb use cases for the bot's /verb and the Mini App's Verbs page (docs/verbs/contract.md).

The conjugator (our own offline service) owns the grammar: matching, forms, variants, stems.
This layer adds what is per user (recent verbs, the collection, the level's tenses, practice)
and the drill payload. Nothing here calls the LLM.

Lookups are counted (`verb_lookups`) but not limited: they cost no paid provider calls.
Callers parse first, then look up; they own presentation and error reporting, and
conjugator errors (ConjugatorError) propagate.
"""
import unicodedata
from dataclasses import dataclass
from typing import Literal, Optional, Union

from flashcard.schemas.user import UserId
from flashcard.schemas.verbs import PERSONS, TENSE_IDS, Conjugation, Form, Match, Person, Verb
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.user import UserService
from flashcard.services.verb import MAX_QUERY_CHARS, SUGGEST_LIMIT, VerbService
from flashcard.services.verb_practice import PracticeResult, VerbPracticeService
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

# The tenses that matter at each target level (contract section 4, `level_tenses`).
# A1-B1: the six core tenses. B2 adds the subjunctive, the conditional past and the remaining
# everyday compound tenses. C1-C2: all 15, including the literary passato/trapassato remoto.
CORE_TENSES = (
    "indicativo-presente", "indicativo-passato_prossimo", "indicativo-imperfetto",
    "indicativo-futuro_semplice", "imperativo-presente", "condizionale-presente",
)
B2_TENSES = CORE_TENSES + (
    "indicativo-trapassato_prossimo", "indicativo-futuro_anteriore",
    "congiuntivo-presente", "congiuntivo-imperfetto", "congiuntivo-passato", "congiuntivo-trapassato",
    "condizionale-passato",
)
LEVEL_TENSES: dict[str, tuple[str, ...]] = {
    "A1": CORE_TENSES, "A2": CORE_TENSES, "B1": CORE_TENSES,
    "B2": B2_TENSES, "C1": TENSE_IDS, "C2": TENSE_IDS,
}

# Subject words a drill answer may start with; longest first (contract section 4, "Drill").
STRIP_PREFIXES = ["che io", "che tu", "che lui", "che lei", "che noi", "che voi", "che loro",
                  "io", "tu", "lui", "lei", "noi", "voi", "loro", "che"]
SUGGEST_MIN_CHARS = 2


def level_tenses(level: str) -> list[str]:
    """Tense ids for a target level; an unknown level gets the core tenses."""
    return list(LEVEL_TENSES.get(level, CORE_TENSES))


def plain(text: str) -> str:
    """Accents removed (NFD, combining marks dropped)."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def _answer_text(text: str) -> str:
    """An accepted answer as the client compares it: NFC, lowercase, plain apostrophe."""
    return unicodedata.normalize("NFC", text).replace("’", "'").lower()


# ---- results ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NoVerb:
    pass


@dataclass(frozen=True)
class InvalidVerb:
    verb: str


ParseResult = Union[str, NoVerb, InvalidVerb]


@dataclass(frozen=True)
class Found:
    match: Match
    verb: Verb
    level_tenses: list[str]
    # The first translation of the user's card for this infinitive, if they have one.
    meaning: Optional[str]
    in_collection: bool


@dataclass(frozen=True)
class NotFound:
    query: str
    suggestions: list[str]


LookupResult = Union[Found, NotFound]


@dataclass(frozen=True)
class Conjugated:
    """A verb shown again (bot navigation): no user data, not counted."""
    verb: Verb


@dataclass(frozen=True)
class CollectionVerb:
    infinitive: str
    expression_id: str
    meaning: Optional[str]


@dataclass(frozen=True)
class Home:
    recent: list[str]
    collection: list[CollectionVerb]


Note = Literal["feminine", "variant"]


@dataclass(frozen=True)
class Accepted:
    text: str
    # None for the primary form and untagged variants of equal standing.
    note: Optional[Note]


@dataclass(frozen=True)
class StemHint:
    """The stem is irregular, the ending regular: show the stem."""
    stem: str


@dataclass(frozen=True)
class FormHint:
    """The whole form is irregular."""


Hint = Union[StemHint, FormHint]


@dataclass(frozen=True)
class DrillItem:
    person: Person
    primary: str
    accepted: list[Accepted]
    accepted_plain: list[str]
    hint: Optional[Hint]


@dataclass(frozen=True)
class Drill:
    infinitive: str
    tense_id: str
    strip_prefixes: list[str]
    items: list[DrillItem]


@dataclass(frozen=True)
class NoSuchVerb:
    """The infinitive is not a verb, or the verb has no such tense."""


@dataclass(frozen=True)
class InvalidPractice:
    reason: str


@dataclass(frozen=True)
class Recorded:
    pass


def _hint(primary: Form) -> Optional[Hint]:
    """For a simple form: its stem when only the stem is irregular, else a plain "irregular" hint."""
    parts = primary.parts
    if parts.kind != "simple":
        return None
    if parts.irregular_stem and parts.ending:
        return StemHint(stem=parts.stem)
    return FormHint() if primary.irregular else None


class VerbUseCases:
    def __init__(self, verb_service: VerbService, consumption_service: ConsumptionService,
                 user_service: UserService, expression_service: ExpressionService,
                 practice_service: VerbPracticeService):
        self.verbs = verb_service
        self.consumption = consumption_service
        self.users = user_service
        self.expressions = expression_service
        self.practice = practice_service

    # ---- search ------------------------------------------------------------------------------------

    def parse(self, text: Optional[str]) -> ParseResult:
        """The normalized query (up to 4 words, 60 characters), or why the input is not one."""
        raw = (text or "").strip()
        if not raw:
            return NoVerb()
        query = self.verbs.normalize(raw)
        if not self.verbs.is_valid_verb(query):
            return InvalidVerb(verb=raw)
        return query

    async def suggest(self, prefix: str) -> list[str]:
        """Infinitives starting with `prefix`; [] below 2 characters or for text no verb starts with."""
        query = self.verbs.normalize(prefix or "")
        if len(query) < SUGGEST_MIN_CHARS or len(query) > MAX_QUERY_CHARS or not self.verbs.is_valid_verb(query):
            return []
        return await self.verbs.suggest(query, SUGGEST_LIMIT)

    async def lookup(self, user_id: UserId, query: str) -> LookupResult:
        """
        Look up a query returned by `parse` (raises ValueError for anything else). A found verb
        goes first in the user's recent verbs and counts as a lookup.
        """
        if self.parse(query) != query:
            raise ValueError(f"Not a parsed verb: {query!r}")
        answer = await self.verbs.conjugate(query)
        if not isinstance(answer, Conjugation):
            return NotFound(query=query, suggestions=answer.suggestions)

        verb = answer.verb
        await self.users.remember_verb(user_id, verb.infinitive)
        await self.consumption.increment(user_id, "verb_lookups")
        user = await self.users.get_user(user_id)
        card = await self.expressions.find_word(user_id, verb.infinitive)
        return Found(match=answer.match, verb=verb, level_tenses=level_tenses(user.target_level),
                     meaning=card.meaning if card else None, in_collection=card is not None)

    async def conjugation(self, infinitive: str) -> Union[Conjugated, NotFound]:
        """An already shown verb again (bot navigation); not counted, not recorded."""
        answer = await self.verbs.conjugate(infinitive)
        if not isinstance(answer, Conjugation):
            return NotFound(query=infinitive, suggestions=answer.suggestions)
        return Conjugated(verb=answer.verb)

    async def home(self, user_id: UserId) -> Home:
        """Recent verbs and the user's cards that are verb infinitives (newest first)."""
        user = await self.users.get_user(user_id)
        return Home(recent=list(user.verbs_recent), collection=await self._collection_verbs(user_id))

    async def _collection_verbs(self, user_id: UserId) -> list[CollectionVerb]:
        words = await self.expressions.single_words(user_id)
        if not words:
            return []
        try:
            infinitives = await self.verbs.infinitives(list(dict.fromkeys(w.value for w in words)))
        except Exception:
            # The rest of the page still works; the collection list is just left empty.
            logger.warning("Could not read the collection's verbs from the conjugator", exc_info=True)
            return []
        verbs, seen = [], set()
        for word in words:
            infinitive = infinitives.get(word.value)
            if infinitive and infinitive not in seen:
                seen.add(infinitive)
                verbs.append(CollectionVerb(infinitive=infinitive, expression_id=word.id, meaning=word.meaning))
        return verbs

    # ---- drill -------------------------------------------------------------------------------------

    async def _verb_with_tense(self, infinitive: str, tense_id: str) -> Optional[Verb]:
        if tense_id not in TENSE_IDS or self.parse(infinitive) != infinitive or " " in infinitive:
            return None
        answer = await self.verbs.conjugate(infinitive)
        verb = answer.verb if isinstance(answer, Conjugation) else None
        # Only the verb itself: a form ("vado") or a near miss ("andre") would open another verb.
        if verb is None or verb.infinitive != infinitive or verb.tense(tense_id) is None:
            return None
        return verb

    async def drill(self, infinitive: str, tense_id: str) -> Union[Drill, NoSuchVerb]:
        """The answers a typing drill accepts for one tense; empty slots are left out."""
        verb = await self._verb_with_tense(infinitive, tense_id)
        if verb is None:
            return NoSuchVerb()
        tense = verb.tense(tense_id)
        assert tense is not None  # checked by _verb_with_tense
        items = []
        for slot in tense.slots:
            primary = slot.primary
            if primary is None:
                continue
            accepted: dict[str, Accepted] = {}
            for form in slot.forms:
                text = _answer_text(form.text)
                note: Optional[Note] = None if form.primary or not form.tags else (
                    "feminine" if "feminine" in form.tags else "variant")
                accepted.setdefault(text, Accepted(text=text, note=note))
            items.append(DrillItem(
                person=slot.person, primary=primary.text, accepted=list(accepted.values()),
                accepted_plain=sorted({plain(text) for text in accepted}), hint=_hint(primary)))
        return Drill(infinitive=verb.infinitive, tense_id=tense_id, strip_prefixes=list(STRIP_PREFIXES), items=items)

    async def record_practice(
        self, user_id: UserId, infinitive: str, tense_id: str, score: int, out_of: int, missed: list[str],
    ) -> Union[Recorded, NoSuchVerb, InvalidPractice]:
        """Store one finished drill (contract section 5)."""
        if not 1 <= out_of <= len(PERSONS) or not 0 <= score <= out_of:
            return InvalidPractice("score must be between 0 and out_of (1-6)")
        if any(person not in PERSONS for person in missed) or len(set(missed)) != len(missed):
            return InvalidPractice("missed must be distinct persons")
        if len(missed) > out_of - score:
            return InvalidPractice("more missed persons than wrong answers")
        if await self._verb_with_tense(infinitive, tense_id) is None:
            return NoSuchVerb()
        await self.practice.record(user_id, PracticeResult(
            infinitive=infinitive, tense_id=tense_id, score=score, out_of=out_of,
            missed=[p for p in PERSONS if p in missed]))
        return Recorded()
