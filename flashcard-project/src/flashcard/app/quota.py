"""
Quota: daily generation limits per tier, the trial, and own-key handling.

Use cases ask `check` before an LLM call and `record` once the user receives
what was generated. Only delivered results count; failed generations are free.

Cards are paid in credits: a new card costs CARD_CREDITS, a refreshed card part
SECTION_CREDITS. Stories and audio keep their own plain daily counts.
"""
from dataclasses import dataclass
from typing import Literal, Optional, Union

from flashcard.schemas.user import UserId
from flashcard.schemas.user import UserDB, UserTier
from flashcard.services.consumption import ConsumptionService
from flashcard.utils.time import now_utc


# Normal-tier users get plus limits for this many days after created_at.
TRIAL_DAYS = 14

# Credits a card generation costs. A part refresh writes about half a card, so it costs half.
CARD_CREDITS = 2
SECTION_CREDITS = 1

Kind = Literal["cards", "stories"]

_METRICS: dict[str, str] = {"cards": "cards_generated", "stories": "stories_generated"}
# The daily limit of a kind is read from TIER_LIMITS_<TIER>_<suffix>.
_LIMIT_SUFFIX: dict[str, str] = {"cards": "CREDITS", "stories": "STORIES", "audio": "AUDIO"}


@dataclass(frozen=True)
class Allowed:
    # Own-key usage is unlimited and counted apart from system-key usage.
    uses_own_key: bool
    # Credits `record` charges; 0 for kinds not paid in credits.
    credits: int = 0


@dataclass(frozen=True)
class QuotaExceeded:
    tier: str
    limit: int


QuotaResult = Union[Allowed, QuotaExceeded]


@dataclass(frozen=True)
class Usage:
    """
    Today's use of a kind and its daily limit; `limit` is None when nothing limits the user.
    For cards both are credits.
    """
    used: int
    limit: Optional[int]


class QuotaPolicy:
    def __init__(self, consumption_service: ConsumptionService, settings):
        """`settings`: provides the TIER_LIMITS_* values, read on every check."""
        self.consumption = consumption_service
        self.settings = settings

    def check(self, user: UserDB, kind: Kind, credits: int = CARD_CREDITS) -> QuotaResult:
        """
        Whether the user may generate one more `kind` today. For cards, `credits` is what this
        generation costs: CARD_CREDITS for a new card, SECTION_CREDITS for a refreshed part.
        """
        cost = credits if kind == "cards" else 0
        uses_own_key = user.api_config is not None
        if uses_own_key or user.tier == UserTier.admin:
            return Allowed(uses_own_key=uses_own_key, credits=cost)

        limit = self.limit(user, kind)
        if self._used(user, kind, uses_own_key=False) + max(cost, 1) > limit:
            return QuotaExceeded(tier=user.tier.value, limit=limit)
        return Allowed(uses_own_key=False, credits=cost)

    def usage(self, user: UserDB, kind: Kind) -> Usage:
        """Today's use of `kind` for display. Own-key and admin use is not limited."""
        uses_own_key = user.api_config is not None
        unlimited = uses_own_key or user.tier == UserTier.admin
        return Usage(used=self._used(user, kind, uses_own_key=uses_own_key),
                     limit=None if unlimited else self.limit(user, kind))

    async def record(self, user_id: UserId, kind: Kind, allowed: Allowed) -> None:
        """Count one delivered `kind`, and the credits `check` priced it at, under the bucket `check` chose."""
        extra = {"credits": allowed.credits} if allowed.credits else {}
        await self.consumption.increment(user_id, _METRICS[kind], uses_own_key=allowed.uses_own_key, **extra)

    def check_audio(self, user: UserDB) -> QuotaResult:
        """Whether the user may generate one more audio clip today. An own LLM key does not pay for audio."""
        if user.tier == UserTier.admin:
            return Allowed(uses_own_key=False)
        limit = self.limit(user, "audio")
        if self.consumption.resolve_consumption(user.consumption).audio_generated >= limit:
            return QuotaExceeded(tier=user.tier.value, limit=limit)
        return Allowed(uses_own_key=False)

    async def record_audio(self, user_id: UserId) -> None:
        await self.consumption.increment(user_id, "audio_generated")

    def limit(self, user: UserDB, kind: str) -> int:
        """Daily limit for the user's tier (credits for cards); normal users in their trial get plus limits."""
        tier = UserTier.plus if self._in_trial(user) else user.tier
        return getattr(self.settings, f"TIER_LIMITS_{tier.name.upper()}_{_LIMIT_SUFFIX[kind]}")

    def _used(self, user: UserDB, kind: Kind, *, uses_own_key: bool) -> int:
        consumption = self.consumption.resolve_consumption(user.consumption)
        counts = consumption.user_api if uses_own_key else consumption.system_api
        return counts.credits_used if kind == "cards" else getattr(counts, _METRICS[kind], 0)

    @staticmethod
    def _in_trial(user: UserDB) -> bool:
        if user.tier != UserTier.normal:
            return False
        # No created_at yet: the trial has not started, so it is still on.
        if user.created_at is None:
            return True
        return (now_utc() - user.created_at).days < TRIAL_DAYS
