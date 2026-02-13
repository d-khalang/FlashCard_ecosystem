import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    BOT_TOKEN: str
    LOGGER_BOT_TOKEN: str
    ADMIN_ID: int
    WEBHOOK_BASE: str
    WEBHOOK_PATH: str
    WEBHOOK_SECRET: str
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

@lru_cache
def get_setting() -> Settings:
    return Settings()


settings = get_setting()
print("admin id: ", settings.ADMIN_ID)
