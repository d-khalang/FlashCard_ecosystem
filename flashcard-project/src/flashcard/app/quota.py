"""
Quota: daily generation limits per tier, the trial, and own-key handling.

Use cases ask `check` before an LLM call and `record` once the user receives
what was generated. Only delivered results count; failed generations are free.
"""
from dataclasses import dataclass
from typing import Literal, Union

from flashcard.app.types import UserId
from flashcard.schemas.user import UserDB, UserTier
from flashcard.services.consumption import ConsumptionService
from flashcard.utils.logger import get_logger
from flashcard.utils.time import now_utc, parse_iso

logger = get_logger(__name__)

# Normal-tier users get plus limits for this many days after created_at.
TRIAL_DAYS = 14

Kind = Literal["cards", "stories"]

_METRICS: dict[str, str] = {"cards": "cards_generated", "stories": "stories_generated"}


@dataclass(frozen=True)
class Allowed:
    # Own-key usage is unlimited and counted apart from system-key usage.
    uses_own_key: bool


@dataclass(frozen=True)
class QuotaExceeded:
    tier: str
    limit: int


QuotaResult = Union[Allowed, QuotaExceeded]


class QuotaPolicy:
    def __init__(self, consumption_service: ConsumptionService, settings):
        """`settings`: provides the TIER_LIMITS_* values, read on every check."""
        self.consumption = consumption_service
        self.settings = settings

    def check(self, user: UserDB, kind: Kind) -> QuotaResult:
        """Whether the user may generate one more `kind` today."""
        uses_own_key = user.api_config is not None
        if uses_own_key or user.tier == UserTier.admin:
            return Allowed(uses_own_key=uses_own_key)

        limit = self.limit(user, kind)
        used = getattr(self.consumption.resolve_consumption(user.consumption).system_api, _METRICS[kind], 0)
        if used >= limit:
            return QuotaExceeded(tier=user.tier.value, limit=limit)
        return Allowed(uses_own_key=False)

    async def record(self, user_id: UserId, kind: Kind, allowed: Allowed) -> None:
        """Count one delivered `kind` under the bucket `check` chose."""
        await self.consumption.increment(user_id, _METRICS[kind], uses_own_key=allowed.uses_own_key)

    def limit(self, user: UserDB, kind: Kind) -> int:
        """Daily limit for the user's tier; normal users in their trial get plus limits."""
        tier = UserTier.plus if self._in_trial(user) else user.tier
        return getattr(self.settings, f"TIER_LIMITS_{tier.name.upper()}_{kind.upper()}")

    @staticmethod
    def _in_trial(user: UserDB) -> bool:
        if user.tier != UserTier.normal:
            return False
        # No created_at yet: the trial has not started, so it is still on.
        if user.created_at is None:
            return True
        try:
            return (now_utc() - parse_iso(user.created_at)).days < TRIAL_DAYS
        except (ValueError, TypeError):  # unparseable or timezone-naive date
            logger.warning("Unreadable created_at %r for user %s; no trial", user.created_at, user.user_id)
            return False
