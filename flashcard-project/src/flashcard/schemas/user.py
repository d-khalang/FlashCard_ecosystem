from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from flashcard.schemas.languages import LanguageCode, LanguageLevel

class UserAPIConfig(BaseModel):
    provider: str = Field("gemini", description="LLM Provider e.g. openai, gemini")
    model: str = Field("gemini-2.5-flash", description="Model name e.g. gemini-2.5-flash")
    api_key: str = Field(..., description="API Key")


class UserConsumption(BaseModel):
    review_today: int = Field(0, description="Number of reviews done today")
    saved_today: int = Field(0, description="Number of flashcards saved today")
    story_today: int = Field(0, description="Number of stories generated today")

class UserDB(BaseModel):
    user_id: str = Field(..., description="User ID as string")
    last_push_at: Optional[str] = Field(None, description="ISO timestamp of last push")
    has_pending: bool = Field(False, description="If user has pending reviews")
    is_active: bool = Field(True, description="If user is active for scheduler")
    
    # Settings
    primary_language: LanguageCode = Field("en", description="Primary interface language (e.g. 'en', 'fa')")
    secondary_language: Optional[LanguageCode] = Field(None, description="Secondary translation language")
    target_level: LanguageLevel = Field("A2", description="Target CEFR level (A1-C2)")
    review_mode: str = Field("standard", description="Review mode: standard or dual")
    review_interval_minutes: int = Field(30, description="Minutes between review batches")
    api_config: Optional[UserAPIConfig] = Field(None, description="Custom User API Config")
    
    # Consumption Tracking
    consumption: UserConsumption = Field(UserConsumption(), description="User Consumption per day")
