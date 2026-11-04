from typing import Annotated, Optional, Union

from fastapi import APIRouter, Query, Response

from flashcard.app.collection import (
    AllDuplicates, BadCursor, Imported as ImportedResult, InvalidLanguage, ItemDetail, ItemPage, NotFound,
    NothingFound, ParseFailed, QueryTooLong, QueryTooShort, TooLong as TooLongResult,
)
from flashcard.app.creation import Saved
from flashcard.app.quota import QuotaExceeded
from flashcard.miniapp.errors import invalid_request, not_found
from flashcard.miniapp.routes.deps import CoreDep, GeneralUser, LlmUser, generating
from flashcard.miniapp.schemas import (
    CollectionDetail, CollectionPage, ImportIn, Imported, QuotaResult, SaveIn, StatusOnly, TooLong,
    detail_out, quota_out, row_out,
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
async def save(body: SaveIn, user_id: GeneralUser, core: CoreDep) -> StatusOnly:
    result = await core.creation_use_cases.save(user_id, body.value)
    return StatusOnly(status="saved" if isinstance(result, Saved) else "already_saved")


@router.post("/import")
async def import_items(
    body: ImportIn, user_id: LlmUser, core: CoreDep,
) -> Union[Imported, TooLong, StatusOnly, QuotaResult]:
    result = await generating(core.collection_use_cases.import_items(user_id, body.text))
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
