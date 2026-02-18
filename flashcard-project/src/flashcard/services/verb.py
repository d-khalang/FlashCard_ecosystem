import re
from typing import Optional

from aiogram.types import InlineKeyboardMarkup

from flashcard.settings import settings
from flashcard.schemas.conjugations import ConjugationDBResponse, ConjugationAPIResponse, ConjugationResponse
from flashcard.telegram.keyboards import get_verb_keyboard
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

class VerbService:
    REGEX_VERB = r"^[A-Za-zÀ-ÖØ-öø-ÿ']+$"

    def __init__(self, cols: dict, http_client=None):
        self.cols = cols
        self.http_client = http_client

    def is_valid_verb(self, verb: str) -> bool:
        """
        Validates if the input string is a valid verb format.
        """
        if not verb:
            return False
        
        # Clean the verb: remove /verb command if present, strip whitespace
        cleaned = verb.replace("/verb", "").strip()
        
        if len(cleaned) == 0:
            return False
            
        return bool(re.match(self.REGEX_VERB, cleaned))


    def extract_verb(self, message_text: str) -> Optional[str]:
        """
        Extracts the verb from the message text.
        Returns None if extraction fails or text is too short logic applies.
        """
        if not message_text:
            return None
            
        clean_verb = message_text.replace("/verb", "").strip()
        
        # Basic check to avoid empty strings after strip if message was just "/verb"
        if not clean_verb:
            return None
            
        return clean_verb

    def get_verb_keyboard(self, data: ConjugationResponse) -> InlineKeyboardMarkup:
        """
        Gets the verb keyboard.
        """
        return get_verb_keyboard(data)

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
            return await self.cols['conjugation'].find_one({'verb': verb})
        except Exception as e:
            logger.error(f"Failed to get verb from db: {e}")
            return None


    async def get_verb_from_api(self, verb: str) -> Optional[ConjugationResponse]:
        """
        Gets the verb from the API.
        """
        try:
            res = await self.http_client.get(f"{settings.SCRAPER_URL}:{settings.SCRAPER_PORT}/conjugate",
                params={"v": verb},
                headers={"X-API-Key": settings.SCRAPER_API_KEY})
            
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
            await self.cols['conjugation'].replace_one(
                {'verb': verb}, 
                db_entry.model_dump(), 
                upsert=True
            )
            logger.info(f"Saved verb {verb} to DB")
        except Exception as e:
            logger.error(f"Failed to save verb {verb} to DB: {e}")

