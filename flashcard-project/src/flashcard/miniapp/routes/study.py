from typing import Union

from fastapi import APIRouter, Request

from flashcard.app.quota import QuotaExceeded
from flashcard.app.review import CardNotFound, Graded, NoCandidate, NotPending
from flashcard.app.study import Delivered, GenerationFailed, NothingToUndo, Refreshed, Undone
from flashcard.miniapp.errors import generation_failed, invalid_request, not_found
from flashcard.miniapp.routes.deps import CoreDep, GeneralUser, LlmUser
from flashcard.miniapp.schemas import (
    CurrentOut, GradedOut, GradeIn, QuotaResult, ReadyCard, RefreshIn, StatusOnly, UndoneOut,
    quota_out, study_card_out,
)

router = APIRouter(prefix="/study")


@router.get("/current")
async def current(user_id: GeneralUser, core: CoreDep) -> CurrentOut:
    state = await core.study_use_cases.current(user_id)
    return CurrentOut(
        card=study_card_out(state.card) if state.card is not None else None,
        undo_available=state.undo_available,
    )


@router.post("/next")
async def next_card(
    user_id: LlmUser, core: CoreDep, request: Request,
) -> Union[ReadyCard, StatusOnly, QuotaResult]:
    prepared = request.app.state.prepared
    result = await core.study_use_cases.next(user_id, take_prepared=lambda: prepared.take(user_id))
    if isinstance(result, Delivered):
        return ReadyCard(card=study_card_out(result.card))
    if isinstance(result, NoCandidate):
        return StatusOnly(status="none")
    if isinstance(result, QuotaExceeded):
        return quota_out(result)
    assert isinstance(result, GenerationFailed)
    raise generation_failed()


@router.post("/prepare", status_code=202)
async def prepare(user_id: LlmUser, core: CoreDep, request: Request) -> dict:
    request.app.state.prepared.start(user_id, lambda: core.study_use_cases.prepare(user_id))
    return {}


@router.post("/grade")
async def grade(body: GradeIn, user_id: GeneralUser, core: CoreDep) -> Union[GradedOut, StatusOnly]:
    try:
        result = await core.study_use_cases.grade(
            user_id, body.expression_id, body.grade, body.direction, delivery_id=body.delivery_id)
    except ValueError:
        raise invalid_request() from None
    if isinstance(result, Graded):
        return GradedOut()
    if isinstance(result, NotPending):
        return StatusOnly(status="not_pending")
    assert isinstance(result, CardNotFound)
    raise not_found()


@router.post("/undo")
async def undo(user_id: GeneralUser, core: CoreDep) -> Union[UndoneOut, StatusOnly]:
    result = await core.study_use_cases.undo(user_id)
    if isinstance(result, Undone):
        return UndoneOut(card=study_card_out(result.card))
    assert isinstance(result, NothingToUndo)
    return StatusOnly(status="nothing_to_undo")


@router.post("/refresh")
async def refresh(body: RefreshIn, user_id: LlmUser, core: CoreDep) -> Union[ReadyCard, StatusOnly, QuotaResult]:
    result = await core.study_use_cases.refresh_section(user_id, body.delivery_id, body.section)
    if isinstance(result, Refreshed):
        return ReadyCard(card=study_card_out(result.card))
    if isinstance(result, NotPending):
        return StatusOnly(status="not_pending")
    if isinstance(result, QuotaExceeded):
        return quota_out(result)
    assert isinstance(result, GenerationFailed)
    raise generation_failed()
