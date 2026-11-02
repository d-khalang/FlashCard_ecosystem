import re
from dataclasses import dataclass
from typing import Optional

from flashcard.schemas.conjugations import ConjugationDBResponse, ConjugationAPIResponse, ConjugationResponse
from flashcard.utils.logger import get_logger
from flashcard.utils.tracing import observe

logger = get_logger(__name__)


@dataclass(frozen=True)
class ScraperConfig:
    url: str
    port: int
    api_key: str

    @classmethod
    def from_settings(cls, settings) -> Optional["ScraperConfig"]:
        """None when incomplete (Settings requires all three when conjugation is on)."""
        if not settings.SCRAPER_URL or settings.SCRAPER_PORT is None or not settings.SCRAPER_API_KEY:
            return None
        return cls(url=settings.SCRAPER_URL, port=settings.SCRAPER_PORT, api_key=settings.SCRAPER_API_KEY)


class VerbService:
    REGEX_VERB = r"^[A-Za-zÀ-ÖØ-öø-ÿ']+$"

    def __init__(self, conjugations, http_client=None, scraper: Optional[ScraperConfig] = None):
        """`conjugations`: the conjugation cache collection; `scraper`: the conjugation API."""
        self.conjugations = conjugations
        self.http_client = http_client
        self.scraper = scraper

    def is_valid_verb(self, verb: str) -> bool:
        """
        Validates the verb's format only. Callers pass the verb itself: command
        parsing (e.g. "/verb ...") belongs to the Telegram handler.
        """
        if not isinstance(verb, str) or not verb.strip():
            return False
        return bool(re.match(self.REGEX_VERB, verb.strip()))


    @observe(name="VerbService.get_verb_data")
    async def get_verb_data(self, verb: str) -> Optional[ConjugationResponse]:
        """
        Orchestrates retrieving verb data:
        1. Checks DB.
        2. If not in DB, checks API.
        3. If found in API, saves to DB.
        Returns ConjugationResponse or None if not found/error.
        """
        # 1. Check DB
        verb_db = await self.get_verb_from_db(verb)
        if verb_db:
            try:
                db_response = ConjugationDBResponse.model_validate(verb_db)
                return db_response.data
            except Exception as e:
                logger.error(f"Error validating DB data for verb {verb}: {e}")
                # Fallback to API if DB data is corrupted? Or just return None?
                # For now let's try API if DB fails validation, or we could just error out.
                # Let's proceed to API as fallback.
                pass

        # 2. Check API
        verb_api_response = await self.get_verb_from_api(verb)
        if not verb_api_response:
            return None

        # 3. Save to DB (Background task or await? Await is safer for consistency)
        await self._save_verb_to_db(verb, verb_api_response)

        return verb_api_response


    async def get_verb_from_db(self, verb: str) -> Optional[dict]:
        """
        Gets the verb from the database. returns None if not found.
        """
        try:
            return await self.conjugations.find_one({'verb': verb})
        except Exception as e:
            logger.error(f"Failed to get verb from db: {e}")
            return None


    async def get_verb_from_api(self, verb: str) -> Optional[ConjugationResponse]:
        """
        Gets the verb from the API.
        """
        if self.scraper is None:
            raise RuntimeError("Conjugation service is enabled but its settings are incomplete")

        try:
            res = await self.http_client.get(f"{self.scraper.url}:{self.scraper.port}/conjugate",
                params={"v": verb},
                headers={"X-API-Key": self.scraper.api_key})
            
            if res.status_code != 200:
                logger.warning(f"API returned status {res.status_code} for verb {verb}")
                return None
            
            res_json = res.json()
            api_response = ConjugationAPIResponse.model_validate(res_json)
            
            if api_response.success and api_response.data:
                return api_response.data
            else:
                logger.warning(f"API success=False or no data for verb {verb}: {api_response.error}")
                return None

        except Exception as e:
            logger.error(f"Failed to get verb from api: {e}")
            raise


    async def _save_verb_to_db(self, verb: str, data: ConjugationResponse):
        """
        Saves the verb data to the database using ConjugationDBResponse schema.
        """
        try:
            db_entry = ConjugationDBResponse(verb=verb, data=data)
            # Use upsert to prevent duplicates if created in parallel
            await self.conjugations.replace_one(
                {'verb': verb}, 
                db_entry.model_dump(), 
                upsert=True
            )
            logger.info(f"Saved verb {verb} to DB")
        except Exception as e:
            logger.error(f"Failed to save verb {verb} to DB: {e}")

