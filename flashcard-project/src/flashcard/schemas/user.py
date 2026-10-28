from datetime import datetime
from typing import Literal, Optional, get_args
from enum import Enum
from pydantic import BaseModel, Field, field_validator
from flashcard.schemas.languages import LanguageCode, LanguageLevel
from flashcard.utils.logger import get_logger
from flashcard.utils.time import iso_z, now_utc

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

# Rules for the user's settings, enforced by UserService's setters.
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 240
ReviewMode = Literal["standard", "dual"]
# Stored as the secondary language when the user turns it off.
NO_LANGUAGE = "none"


class CurrentReview(BaseModel):
    """The delivered card still waiting for a grade; replaced by the next one."""
    expression_id: str = Field(..., description="Reviewed expression ObjectId as string")
    # "unknown" only for reviews backfilled from legacy fields; either direction's grade clears it.
    direction: Literal["forward", "reverse", "unknown"]
    message_id: int = Field(..., description="Telegram message that carries the card")
    sent_at: str = Field(..., description="ISO timestamp of delivery")


class UserTier(str, Enum):
    admin = "admin"
    digi = "digi"
    plus = "plus"
    normal = "normal"

class UserDB(BaseModel):
    user_id: str = Field(..., description="User ID as string")
    username: Optional[str] = Field(None, description="Telegram username")
    created_at: Optional[str] = Field(None, description="ISO timestamp of user creation (Trial start)")
    tier: UserTier = Field(UserTier.normal, description="User subscription tier")
    last_push_at: Optional[str] = Field(None, description="ISO timestamp of last push")
    last_reviewed_at: Optional[str] = Field(None, description="ISO timestamp of last review interaction")
    last_seen_at: Optional[str] = Field(None, description="ISO timestamp of the user's last interaction with the bot")
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
        description="Secondary translation language",
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

    @property
    def secondary_translation(self) -> Optional[str]:
        """The secondary language to translate into; None when unset or turned off."""
        if self.secondary_language in (None, NO_LANGUAGE):
            return None
        return self.secondary_language

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
