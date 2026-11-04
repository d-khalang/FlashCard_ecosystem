from typing import Annotated, Optional, Union

from fastapi import APIRouter, Query, Request, Response

from flashcard.app.collection import (
    AllDuplicates, BadCursor, Imported as ImportedResult, InvalidLanguage, ItemDetail, ItemPage, NotFound,
    NothingFound, ParseFailed, QueryTooLong, QueryTooShort, TooLong as TooLongResult,
)
from flashcard.app.creation import InvalidInput, Saved, TooMany
from flashcard.app.quota import QuotaExceeded
from flashcard.miniapp.errors import invalid_request, not_found
from flashcard.miniapp.routes.deps import CoreDep, GeneralUser, LlmUser, generating, generation_gate, refuse
from flashcard.miniapp.schemas import (
    CollectionDetail, CollectionPage, ImportIn, Imported, QuotaResult, SaveIn, SaveInvalid, StatusOnly,
    TooLong, TooManyWords, detail_out, quota_out, row_out,
)

router = APIRouter(prefix="/collection")


@router.get("")
async def list_items(
    user_id: GeneralUser,
    core: CoreDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    cursor: Annotated[Optional[str], Query(max_length=64)] = None,
    q: Annotated[Optional[str], Query(max_length=200)] = None,
) -> CollectionPage:
    result = await core.collection_use_cases.list_page(user_id, limit=limit, cursor=cursor, query=q)
    if isinstance(result, ItemPage):
        return CollectionPage(items=[row_out(i) for i in result.items], next_cursor=result.next_cursor)
    if isinstance(result, QueryTooShort):
        raise invalid_request("Search needs at least 2 characters.")
    if isinstance(result, QueryTooLong):
        raise invalid_request("Search text is too long.")
    assert isinstance(result, BadCursor)
    raise invalid_request("Invalid cursor.")


@router.post("", status_code=201)
async def save(
    body: SaveIn, user_id: GeneralUser, core: CoreDep, request: Request, response: Response,
) -> Union[StatusOnly, SaveInvalid, TooManyWords]:
    result = await core.creation_use_cases.save_word(
        user_id, body.value, max_words=request.app.state.settings.MINIAPP_MAX_WORDS)
    if isinstance(result, InvalidInput):
        response.status_code = 200
        return SaveInvalid(suggestions=result.suggestions)
    if isinstance(result, TooMany):
        response.status_code = 200
        return TooManyWords(limit=result.limit)
    return StatusOnly(status="saved" if isinstance(result, Saved) else "already_saved")


@router.post("/import")
async def import_items(
    body: ImportIn, caller: LlmUser, core: CoreDep, request: Request,
) -> Union[Imported, TooLong, TooManyWords, StatusOnly, QuotaResult]:
    result = await generating(core.collection_use_cases.import_items(
        caller.user_id, body.text, max_words=request.app.state.settings.MINIAPP_MAX_WORDS,
        before_generation=generation_gate(request, caller)))
    refuse(result)
    if isinstance(result, TooMany):
        return TooManyWords(limit=result.limit)
    if isinstance(result, ImportedResult):
        return Imported(items=result.items)
    if isinstance(result, TooLongResult):
        return TooLong(limit=result.limit)
    if isinstance(result, QuotaExceeded):
        return quota_out(result)
    if isinstance(result, AllDuplicates):
        return StatusOnly(status="all_duplicates")
    if isinstance(result, ParseFailed):
        return StatusOnly(status="parse_failed")
    if isinstance(result, NothingFound):
        return StatusOnly(status="nothing_found")
    assert isinstance(result, InvalidLanguage)
    return StatusOnly(status="invalid_language")


@router.get("/{expression_id}")
async def detail(expression_id: str, user_id: GeneralUser, core: CoreDep) -> CollectionDetail:
    result = await core.collection_use_cases.detail(user_id, expression_id)
    if isinstance(result, NotFound):
        raise not_found()
    assert isinstance(result, ItemDetail)
    return detail_out(result)


@router.delete("/{expression_id}", status_code=204)
async def remove(expression_id: str, user_id: GeneralUser, core: CoreDep) -> Response:
    result = await core.collection_use_cases.remove(user_id, expression_id)
    if isinstance(result, NotFound):
        raise not_found()
    return Response(status_code=204)
