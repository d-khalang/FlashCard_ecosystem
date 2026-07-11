from datetime import datetime
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field
from flashcard.schemas.languages import LanguageCode, LanguageLevel
from flashcard.settings import settings
from flashcard.utils.time import iso_z, now_utc

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
    has_pending: bool = Field(False, description="If user has pending reviews")
    is_active: bool = Field(True, description="If user is active for scheduler")
    
    # Settings
    primary_language: LanguageCode = Field(
        default_factory=lambda: settings.DEFAULT_PRIMARY_LANGUAGE,
        description="Primary translation language (e.g. 'en', 'fa')",
    )
    secondary_language: Optional[LanguageCode] = Field(
        default_factory=lambda: settings.DEFAULT_SECONDARY_LANGUAGE,
        description="Secondary translation language",
    )
    target_level: LanguageLevel = Field(
        default_factory=lambda: settings.DEFAULT_TARGET_LEVEL,
        description="Target CEFR level (A1-C2)",
    )
    review_mode: str = Field("standard", description="Review mode: standard or dual")
    review_interval_minutes: int = Field(30, description="Minutes between review batches")
    api_config: Optional[UserAPIConfig] = Field(None, description="Custom User API Config")
    
    # Onboarding
    onboarding_step: int = Field(0, description="Onboarding progress: 0=new, 1=first save seen, 2=first review seen")
    
    # Consumption Tracking
    consumption: UserConsumption = Field(UserConsumption(), description="User Consumption per day")
