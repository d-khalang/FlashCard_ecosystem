from typing import Literal, Optional, get_args
from enum import Enum
from pydantic import BaseModel, Field, field_serializer, field_validator
from flashcard.schemas.languages import NONE_MAP, LanguageCode, LanguageLevel
from flashcard.utils.logger import get_logger
from flashcard.utils.time import UtcDatetime

logger = get_logger(__name__)

class UserAPIConfig(BaseModel):
    provider: str = Field("gemini", description="LLM Provider e.g. openai, gemini")
    model: str = Field("gemini-2.5-flash", description="Model name e.g. gemini-2.5-flash")
    api_key: str = Field(..., description="API Key")


class LLMUsage(BaseModel):
    """Tracks LLM API call counts (daily)."""
    cards_generated: int = Field(0, description="Card generations (text→card, regen, /get, scheduled)")
    stories_generated: int = Field(0, description="Story generations (/story)")

class UserConsumption(BaseModel):
    """Daily consumption tracking with lazy reset."""
    consumption_date: Optional[str] = Field(None, description="ISO date of current daily counters (e.g. '2026-02-19')")
    system_api: LLMUsage = Field(LLMUsage(), description="Usage on system API keys (tier-limited)")
    user_api: LLMUsage = Field(LLMUsage(), description="Usage on user's own API keys")
    verb_lookups: int = Field(0, description="Third-party verb API lookups")

# Telegram user id. Code passes it as an int; documents store it as text, so only the
# services that own a collection convert it, with `stored_user_id`.
UserId = int


def stored_user_id(user_id: UserId) -> str:
    """
    The stored form of a user id. Rejects anything but an int, so a text id cannot slip in,
    and ids below 1 (Telegram user ids are positive).
    """
    if type(user_id) is not int:
        raise TypeError(f"user_id must be an int: {user_id!r}")
    if user_id < 1:
        raise ValueError(f"user_id must be positive: {user_id!r}")
    return str(user_id)


def parse_stored_user_id(value) -> Optional[UserId]:
    """
    The user id a document stores, or None if it is not one. Only the exact text
    `stored_user_id` writes counts ("7", not "007" or "-7"), so writes match the document read.
    """
    if not (isinstance(value, str) and value.isascii() and value.isdecimal()):
        return None
    parsed = int(value)
    return parsed if parsed >= 1 and str(parsed) == value else None


# Rules for the user's settings, enforced by UserService's setters.
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 240
ReviewMode = Literal["standard", "dual"]


class CurrentReview(BaseModel):
    """The delivered card still waiting for a grade; replaced by the next one."""
    expression_id: str = Field(..., description="Reviewed expression ObjectId as string")
    # "unknown" only for reviews backfilled from legacy fields; either direction's grade clears it.
    direction: Literal["forward", "reverse", "unknown"]
    message_id: int = Field(..., description="Telegram message that carries the card")
    sent_at: UtcDatetime = Field(..., description="Delivery time")


class UserTier(str, Enum):
    admin = "admin"
    digi = "digi"
    plus = "plus"
    normal = "normal"

class UserDB(BaseModel):
    user_id: UserId = Field(..., description="Telegram user id (stored as text)")
    username: Optional[str] = Field(None, description="Telegram username")
    created_at: Optional[UtcDatetime] = Field(None, description="User creation (trial start)")
    tier: UserTier = Field(UserTier.normal, description="User subscription tier")
    last_push_at: Optional[UtcDatetime] = Field(None, description="Legacy: last push")
    last_reviewed_at: Optional[UtcDatetime] = Field(None, description="Last graded review")
    last_seen_at: Optional[UtcDatetime] = Field(None, description="The user's last interaction with the bot")
    has_pending: bool = Field(False, description="If user has pending reviews")
    current_review: Optional[CurrentReview] = Field(None, description="Ungraded delivered card, if any")
    is_active: bool = Field(True, description="If user is active for scheduler")
    
    # Settings. No defaults here: UserService fills missing ones from the instance's
    # LanguageConfig, so the config is their only source.
    primary_language: LanguageCode = Field(
        ...,
        description="Primary translation language (e.g. 'en', 'fa')",
    )
    secondary_language: Optional[LanguageCode] = Field(
        ...,
        description="Secondary translation language; None when unset or turned off",
    )
    target_level: LanguageLevel = Field(
        ...,
        description="Target CEFR level (A1-C2)",
    )
    review_mode: ReviewMode = Field("standard", description="Review mode: standard or dual")
    review_interval_minutes: int = Field(30, description="Minutes between review batches")
    api_config: Optional[UserAPIConfig] = Field(None, description="Custom User API Config")
    
    # Onboarding
    onboarding_step: int = Field(0, description="Onboarding progress: 0=new, 1=first save seen, 2=first review seen")
    
    # Consumption Tracking
    consumption: UserConsumption = Field(UserConsumption(), description="User Consumption per day")

    @field_validator("secondary_language", mode="before")
    @classmethod
    def _turned_off_reads_as_none(cls, value):
        """Turned off is stored as null; older documents (and env defaults) may say "none"."""
        if isinstance(value, str) and value.strip().lower() in NONE_MAP:
            return None
        return value

    @field_validator("user_id", mode="before")
    @classmethod
    def _user_id_from_storage(cls, value):
        """Reads the stored text form; anything else but a positive int makes the document unreadable."""
        if type(value) is int:
            stored_user_id(value)  # raises ValueError below 1
            return value
        parsed = parse_stored_user_id(value)
        if parsed is None:
            raise ValueError(f"not a stored user id: {value!r}")
        return parsed

    @field_serializer("user_id")
    def _user_id_to_storage(self, user_id: UserId) -> str:
        """A dump is the document's shape, so it round-trips through storage."""
        return stored_user_id(user_id)

    @field_validator("review_mode", mode="before")
    @classmethod
    def _unknown_review_mode_reads_as_standard(cls, value):
        """
        Reading is forgiving so one bad stored value cannot break the scheduler;
        writing stays strict (UserService.set_review_mode). "standard" is the safe default.
        """
        if value in get_args(ReviewMode):
            return value
        logger.warning("Unknown stored review_mode %r read as 'standard'", value)
        return "standard"
