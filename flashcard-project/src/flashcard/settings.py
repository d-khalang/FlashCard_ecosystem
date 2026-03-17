from functools import lru_cache
from typing import Literal

from pydantic import model_validator
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
    SCRAPER_API_KEY: str
    SCRAPER_URL: str
    SCRAPER_PORT: int
    LOG_LEVEL: str = "INFO"
    SCHEDULER_CHECK_INTERVAL_SECONDS: int = 600  # 10 minutes

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

    @property
    def webhook_url(self) -> str:
        base = self.WEBHOOK_BASE.rstrip("/")
        path = self.WEBHOOK_PATH.lstrip("/")
        return f"{base}/{path}"

    @model_validator(mode="after")
    def validate_webhook_settings(self):
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
