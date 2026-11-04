from typing import Union

from fastapi import APIRouter, Request

from flashcard.app.creation import CardReady, InvalidInput, Unclear
from flashcard.app.quota import QuotaExceeded
from flashcard.miniapp.routes.deps import CoreDep, LlmUser, generating, generation_gate, refuse
from flashcard.miniapp.schemas import (
    PreviewInvalid, PreviewReady, PreviewUnclear, QuotaResult, TextIn, content_out, quota_out,
)

router = APIRouter(prefix="/cards")


@router.post("/preview")
async def preview(
    body: TextIn, caller: LlmUser, core: CoreDep, request: Request,
) -> Union[PreviewReady, PreviewUnclear, PreviewInvalid, QuotaResult]:
    result = await generating(core.creation_use_cases.generate(
        caller.user_id, body.text, before_generation=generation_gate(request, caller)))
    refuse(result)
    if isinstance(result, CardReady):
        return PreviewReady(norm=result.card.norm, content=content_out(result.card))
    if isinstance(result, Unclear):
        return PreviewUnclear(note=result.card.note or None, suggestions=list(result.card.suggestions))
    if isinstance(result, InvalidInput):
        return PreviewInvalid(suggestions=list(result.suggestions))
    assert isinstance(result, QuotaExceeded)
    return quota_out(result)
