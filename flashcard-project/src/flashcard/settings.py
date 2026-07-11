from functools import lru_cache
from typing import Literal, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    BOT_TOKEN: str
    LOGGER_BOT_TOKEN: str
    ADMIN_ID: int
    TELEGRAM_DELIVERY_MODE: Literal["polling", "webhook"] = "polling"
    WEBHOOK_BASE: str = ""
    WEBHOOK_PATH: str = "/webhook/telegram"
    WEBHOOK_SECRET: str = ""
    MONGO_URI: str
    MONGO_DB: str
    COLLECTION_USERS: str
    COLLECTION_EXPRESSION: str
    COLLECTION_CONJUGATION: str
    PORT: int = 8000
    IN_DOCKER: int = 0
    SCRAPER_API_KEY: Optional[str] = None
    SCRAPER_URL: Optional[str] = None
    SCRAPER_PORT: Optional[int] = None
    LOG_LEVEL: str = "INFO"
    LEARNING_LANGUAGE_CODE: str = "it"
    LEARNING_LANGUAGE_NAME: str = "Italian"
    LEARNING_LANGUAGE_FLAG: str = "🇮🇹"
    DEFAULT_PRIMARY_LANGUAGE: str = "en"
    DEFAULT_SECONDARY_LANGUAGE: Optional[str] = None
    DEFAULT_TARGET_LEVEL: str = "A2"
    UI_LOCALE: str = "en"
    ENABLE_CONJUGATION: bool = True
    LANGUAGE_VALIDATOR: str = "auto"
    SCHEDULER_CHECK_INTERVAL_SECONDS: int = 600  # 10 minutes
    LLM_GOOGLE_MODEL: str = "gemini-2.5-flash-lite"
    LLM_GROQ_MODEL: str = "openai/gpt-oss-120b"
    LLM_GROQ_FALLBACK_DELAY_SECONDS: float = 4.0
    LLM_MAX_ATTEMPTS: int = 2

    # ──────────────────────────────────────────────
    # Quota / Tier Limits
    # ──────────────────────────────────────────────
    TIER_LIMITS_NORMAL_CARDS: int = 10
    TIER_LIMITS_NORMAL_STORIES: int = 2
    TIER_LIMITS_DIGI_CARDS: int = 40
    TIER_LIMITS_DIGI_STORIES: int = 3
    TIER_LIMITS_PLUS_CARDS: int = 50
    TIER_LIMITS_PLUS_STORIES: int = 10
    TIER_LIMITS_ADMIN_CARDS: int = 999
    TIER_LIMITS_ADMIN_STORIES: int = 99

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("DEFAULT_SECONDARY_LANGUAGE", "SCRAPER_API_KEY", "SCRAPER_URL", mode="before")
    @classmethod
    def empty_string_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def webhook_url(self) -> str:
        base = self.WEBHOOK_BASE.rstrip("/")
        path = self.WEBHOOK_PATH.lstrip("/")
        return f"{base}/{path}"

    @model_validator(mode="after")
    def validate_webhook_settings(self):
        if self.ENABLE_CONJUGATION:
            missing_conjugation = []
            if not self.SCRAPER_API_KEY:
                missing_conjugation.append("SCRAPER_API_KEY")
            if not self.SCRAPER_URL:
                missing_conjugation.append("SCRAPER_URL")
            if self.SCRAPER_PORT is None:
                missing_conjugation.append("SCRAPER_PORT")
            if missing_conjugation:
                raise ValueError(
                    "Conjugation is enabled and requires these variables: "
                    + ", ".join(missing_conjugation)
                )

        if self.TELEGRAM_DELIVERY_MODE == "webhook":
            missing = []
            if not self.WEBHOOK_BASE.strip():
                missing.append("WEBHOOK_BASE")
            if not self.WEBHOOK_PATH.strip():
                missing.append("WEBHOOK_PATH")
            if not self.WEBHOOK_SECRET.strip():
                missing.append("WEBHOOK_SECRET")
            if missing:
                raise ValueError(
                    "Webhook mode requires these variables: " + ", ".join(missing)
                )
        return self

@lru_cache
def get_setting() -> Settings:
    return Settings()


settings = get_setting()
