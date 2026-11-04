"""Request dependencies: sign-in, the per-user rate limit and access to the core."""
import asyncio
from typing import Annotated, Awaitable, TypeVar

from fastapi import Depends, Request

from flashcard.app.study import GENERATION_TIMEOUT_SECONDS
from flashcard.composition import Core
from flashcard.miniapp.auth import InitDataError, validate_init_data
from flashcard.miniapp.errors import auth_required, generation_failed, not_allowed, rate_limited
from flashcard.schemas.user import UserId
from flashcard.utils.logger import get_logger
from flashcard.utils.time import now_utc

logger = get_logger(__name__)

T = TypeVar("T")


def get_core(request: Request) -> Core:
    return request.app.state.core


CoreDep = Annotated[Core, Depends(get_core)]


async def authenticated_user(request: Request) -> UserId:
    """
    The signed-in Telegram user id, from `Authorization: tma <initData>`. Refuses bad or old data
    (401) and users outside MINIAPP_ALLOWED_USER_IDS (403). Records the user as seen, which
    creates new users and counts as an interaction.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "tma" or not token.strip():
        raise auth_required()
    settings = request.app.state.settings
    try:
        identity = validate_init_data(token.strip(), bot_token=settings.BOT_TOKEN, now=now_utc())
    except InitDataError:
        raise auth_required() from None
    allowed = settings.miniapp_allowed_user_ids
    if allowed is not None and identity.user_id not in allowed:
        raise not_allowed()
    await request.app.state.core.user_service.record_seen(identity.user_id, identity.username)
    return identity.user_id


def _limited(kind: str):
    async def dependency(request: Request, user_id: Annotated[UserId, Depends(authenticated_user)]) -> UserId:
        wait = request.app.state.limiters[kind].hit(user_id)
        if wait:
            raise rate_limited(wait)
        return user_id
    return dependency


# Routes that do not call the LLM: 120 a minute. The routes marked * in the contract: 20 a minute.
GeneralUser = Annotated[UserId, Depends(_limited("general"))]
LlmUser = Annotated[UserId, Depends(_limited("llm"))]


async def generating(work: Awaitable[T]) -> T:
    """Run LLM work under the server-side limit; any failure of it is `generation_failed` (503)."""
    try:
        return await asyncio.wait_for(work, GENERATION_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("Generation failed", exc_info=True)
        raise generation_failed() from None
