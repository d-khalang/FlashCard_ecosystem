import re
import logging
from typing import Optional

from flashcard.settings import settings

logger = logging.getLogger(__name__)

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
            
        if len(message_text) < 7:
            return None
            
        clean_verb = message_text.replace("/verb", "").strip()
        return clean_verb


    async def get_verb_from_db(self, verb: str) -> Optional[dict]:
        """

        Gets the verb from the database. returns None if not found.
        """

        # Example usage of access to db

        try:

            return await self.cols['conjugation'].find_one({'verb': verb})

        except Exception as e:

            logger.error(f"Failed to get verb from db: {e}")

            return None
        

        return None


    async def get_verb_from_api(self, verb: str) -> Optional[dict]:
        """
        Gets the verb from the API.
        """
        try:
            return await self.http_client.get(f"{settings.SCRAPER_URL}:{settings.SCRAPER_PORT}/conjugate",
                params={"v": verb},
                headers={"X-API-Key": settings.SCRAPER_API_KEY})
        except Exception as e:
            logger.error(f"Failed to get verb from api: {e}")
            return None
    
        return None

