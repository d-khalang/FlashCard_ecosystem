from typing import Annotated

from fastapi import APIRouter, Path, Request, Response

from flashcard.app.audio import CardPart, Clip, PartMissing, SpeechFailed
from flashcard.app.quota import QuotaExceeded
from flashcard.app.review import CardNotFound, Throttled
from flashcard.app.speech import UnknownKey
from flashcard.miniapp.errors import audio_limit_reached, not_found, speech_failed
from flashcard.miniapp.routes.deps import CoreDep, GeneralUser, refuse

router = APIRouter(prefix="/audio")

# A key from a preview (`audio` in POST /cards/preview): the hex SHA-256 of what is said.
SpeechKey = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


def _gate(request: Request, user_id):
    limiter = request.app.state.limiters["audio"]

    def gate():
        wait = limiter.hit(user_id)
        return Throttled(retry_after=wait) if wait else None
    return gate


def _answer(result) -> Response:
    refuse(result)
    if isinstance(result, Clip):
        return Response(content=result.audio, media_type="audio/mpeg")
    if isinstance(result, QuotaExceeded):
        raise audio_limit_reached(result.limit)
    if isinstance(result, SpeechFailed):
        raise speech_failed()
    assert isinstance(result, (CardNotFound, PartMissing, UnknownKey))
    raise not_found()


@router.get("/{key}")
async def preview_clip(key: SpeechKey, user_id: GeneralUser, core: CoreDep, request: Request) -> Response:
    """A part of a card preview, by its key. Not cached by the browser; the client keeps replays in memory."""
    return _answer(await core.audio_use_cases.preview_clip(user_id, key, before_generation=_gate(request, user_id)))


@router.get("/{expression_id}/{part}")
async def clip(expression_id: str, part: CardPart, user_id: GeneralUser, core: CoreDep, request: Request) -> Response:
    """One part of the user's saved card as MP3. Not cached by the browser; the client keeps replays in memory."""
    return _answer(await core.audio_use_cases.clip(
        user_id, expression_id, part, before_generation=_gate(request, user_id)))
