"""Request dependencies: sign-in, rate limits, the LLM allowance and access to the core."""
import asyncio
from dataclasses import dataclass
from typing import Annotated, Awaitable, TypeVar

from fastapi import Depends, Request

from flashcard.app.review import GenerationGate, GenerationHeld, Throttled
from flashcard.app.study import GENERATION_TIMEOUT_SECONDS
from flashcard.composition import Core
from flashcard.miniapp.auth import InitDataError, TelegramIdentity, validate_init_data
from flashcard.miniapp.errors import auth_required, generation_failed, not_allowed, rate_limited
from flashcard.schemas.user import UserId, UserTier
from flashcard.utils.logger import get_logger
from flashcard.utils.time import real_now_utc

logger = get_logger(__name__)

T = TypeVar("T")


def get_core(request: Request) -> Core:
    return request.app.state.core


CoreDep = Annotated[Core, Depends(get_core)]


async def verified_identity(request: Request) -> TelegramIdentity:
    """
    The Telegram user from `Authorization: tma <initData>`. Refuses bad or old data (401) and
    users outside MINIAPP_ALLOWED_USER_IDS (403). Writes nothing.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "tma" or not token.strip():
        raise auth_required()
    settings = request.app.state.settings
    try:
        # Telegram signs init data with the real time, so its age never counts from a shifted clock.
        identity = validate_init_data(token.strip(), bot_token=settings.BOT_TOKEN, now=real_now_utc(),
                                      max_age_seconds=settings.MINIAPP_INIT_DATA_MAX_AGE_SECONDS)
    except InitDataError:
        raise auth_required() from None
    allowed = settings.miniapp_allowed_user_ids
    if allowed is not None and identity.user_id not in allowed:
        raise not_allowed()
    return identity


async def _signed_in(request: Request, identity: TelegramIdentity, kind: str) -> UserId:
    """Apply the request limit, then record the user as seen (so a client stuck on 429 writes nothing)."""
    wait = request.app.state.limiters[kind].hit(identity.user_id)
    if wait:
        raise rate_limited(wait)
    # Creates new users and counts as an interaction. A new user can be messaged by the bot only
    # if Telegram says they allow it (otherwise they have not started the chat).
    await request.app.state.core.user_service.record_seen(
        identity.user_id, identity.username, identity.allows_write_to_pm)
    return identity.user_id


async def general_user(request: Request, identity: Annotated[TelegramIdentity, Depends(verified_identity)]) -> UserId:
    return await _signed_in(request, identity, "general")


@dataclass(frozen=True)
class Caller:
    """A signed-in user on a route that may call the LLM."""
    user_id: UserId
    # Admins have no daily allowance of LLM attempts.
    unlimited: bool


async def llm_user(request: Request, identity: Annotated[TelegramIdentity, Depends(verified_identity)]) -> Caller:
    user_id = await _signed_in(request, identity, "general")
    user = await request.app.state.core.user_service.get_user(user_id)
    return Caller(user_id=user_id, unlimited=user.tier == UserTier.admin)


# Routes without an LLM call: 120 a minute. Routes marked * in the contract: 120 a minute to get in,
# and every real LLM call is charged by `generation_gate`.
GeneralUser = Annotated[UserId, Depends(general_user)]
LlmUser = Annotated[Caller, Depends(llm_user)]


def generation_gate(request: Request, caller: Caller, *, honor_hold: bool = False) -> GenerationGate:
    """
    Asked by a use case right before an LLM call really starts. Charges the 20 a minute limit
    and the daily allowance (admins exempt); refuses with Throttled when either is used up,
    and, for study, with GenerationHeld while a recent failure holds generating.
    """
    state = request.app.state

    def gate():
        if honor_hold and state.prepared.held(caller.user_id):
            return GenerationHeld()
        return charge_generation(request, caller)

    return gate


def charge_generation(request: Request, caller: Caller):
    """Charge one LLM attempt: None if allowed, else Throttled."""
    state = request.app.state
    wait = state.limiters["llm"].hit(caller.user_id)
    if not wait and not caller.unlimited:
        wait = state.budget.charge(caller.user_id)
    return Throttled(retry_after=wait) if wait else None


def refuse(result) -> None:
    """Turn a Throttled result into the 429 error."""
    if isinstance(result, Throttled):
        raise rate_limited(result.retry_after)


async def generating(work: Awaitable[T]) -> T:
    """Run LLM work under the server-side limit; any failure of it is `generation_failed` (503)."""
    try:
        return await asyncio.wait_for(work, GENERATION_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("Generation failed", exc_info=True)
        raise generation_failed() from None
