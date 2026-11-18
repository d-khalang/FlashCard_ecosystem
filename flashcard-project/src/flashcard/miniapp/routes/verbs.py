"""
The Verbs page (docs/verbs/contract.md section 4). Only for a language with conjugation; elsewhere
every route answers 404. No route calls the LLM.
"""
from typing import Annotated, Union

from fastapi import APIRouter, Path, Query, Response

from flashcard.app.verb import (
    Drill, Found, InvalidPractice, InvalidVerb, NoSuchVerb, NoVerb, VerbUseCases,
)
from flashcard.composition import Core
from flashcard.miniapp.errors import invalid_request, not_found, verbs_unavailable
from flashcard.miniapp.routes.deps import CoreDep, GeneralUser, SuggestUser
from flashcard.miniapp.schemas import (
    DrillOut, LookupFound, LookupInvalid, LookupNotFound, PracticeIn, VerbsHome, VerbsHomeItem,
    VerbSuggestions, drill_out,
)
from flashcard.services.verb import MAX_QUERY_CHARS, ConjugatorError
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/verbs")

# Generous bounds on the raw text; the use case applies the real rules (contract section 2, "Match").
QueryText = Annotated[str, Query(max_length=200)]


def _verbs(core: Core) -> VerbUseCases:
    if core.verb_use_cases is None:
        raise not_found()
    return core.verb_use_cases


async def _ask(work):
    """Run a conjugator call; when the conjugator fails, answer 503 (the page stays usable)."""
    try:
        return await work
    except ConjugatorError:
        logger.warning("The conjugator failed", exc_info=True)
        raise verbs_unavailable() from None


@router.get("/home")
async def home(user_id: GeneralUser, core: CoreDep) -> VerbsHome:
    result = await _verbs(core).home(user_id)
    return VerbsHome(recent=result.recent, collection=[
        VerbsHomeItem(infinitive=v.infinitive, expression_id=v.expression_id, meaning=v.meaning)
        for v in result.collection])


@router.get("/suggest")
async def suggest(user_id: SuggestUser, core: CoreDep, q: QueryText = "") -> VerbSuggestions:
    return VerbSuggestions(items=await _ask(_verbs(core).suggest(q)))


@router.get("/lookup")
async def lookup(
    user_id: GeneralUser, core: CoreDep, q: QueryText = "",
) -> Union[LookupFound, LookupNotFound, LookupInvalid]:
    verbs = _verbs(core)
    query = verbs.parse(q)
    if isinstance(query, (NoVerb, InvalidVerb)):
        return LookupInvalid(query=q.strip())
    result = await _ask(verbs.lookup(user_id, query))
    if isinstance(result, Found):
        return LookupFound(match=result.match, verb=result.verb, level_tenses=result.level_tenses,
                           meaning=result.meaning, in_collection=result.in_collection)
    return LookupNotFound(query=result.query, suggestions=result.suggestions)


@router.post("/practice", status_code=204)
async def practice(body: PracticeIn, user_id: GeneralUser, core: CoreDep) -> Response:
    result = await _ask(_verbs(core).record_practice(
        user_id, body.infinitive, body.tense_id, body.score, body.out_of, list(body.missed)))
    if isinstance(result, NoSuchVerb):
        raise not_found()
    if isinstance(result, InvalidPractice):
        raise invalid_request(f"Invalid request: {result.reason}.")
    return Response(status_code=204)


@router.get("/{infinitive}/drill/{tense_id}")
async def drill(
    user_id: GeneralUser, core: CoreDep,
    infinitive: Annotated[str, Path(max_length=MAX_QUERY_CHARS)],
    tense_id: Annotated[str, Path(max_length=40)],
) -> DrillOut:
    result = await _ask(_verbs(core).drill(infinitive, tense_id))
    if isinstance(result, NoSuchVerb):
        raise not_found()
    assert isinstance(result, Drill)
    return drill_out(result)
