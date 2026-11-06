from fastapi import APIRouter, Request, Response

from flashcard.app.audio import CardPart, Clip, PartMissing, SpeechFailed
from flashcard.app.quota import QuotaExceeded
from flashcard.app.review import CardNotFound, Throttled
from flashcard.miniapp.errors import audio_limit_reached, not_found, speech_failed
from flashcard.miniapp.routes.deps import CoreDep, GeneralUser, refuse

router = APIRouter(prefix="/audio")


@router.get("/{expression_id}/{part}")
async def clip(expression_id: str, part: CardPart, user_id: GeneralUser, core: CoreDep, request: Request) -> Response:
    """One part of the user's card as MP3. Not cached by the browser; the client keeps replays in memory."""
    limiter = request.app.state.limiters["audio"]

    def gate():
        wait = limiter.hit(user_id)
        return Throttled(retry_after=wait) if wait else None

    result = await core.audio_use_cases.clip(user_id, expression_id, part, before_generation=gate)
    refuse(result)
    if isinstance(result, Clip):
        return Response(content=result.audio, media_type="audio/mpeg")
    if isinstance(result, QuotaExceeded):
        raise audio_limit_reached(result.limit)
    if isinstance(result, SpeechFailed):
        raise speech_failed()
    assert isinstance(result, (CardNotFound, PartMissing))
    raise not_found()
