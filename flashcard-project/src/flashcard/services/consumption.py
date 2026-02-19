from typing import Union

from flashcard.schemas.user import UserConsumption
from flashcard.utils.logger import get_logger
from flashcard.utils.time import now_utc

logger = get_logger(__name__)

# Metrics that live under system_api / user_api
LLM_METRICS = {"cards_generated", "stories_generated"}

# Metrics at the top level of consumption
TOP_LEVEL_METRICS = {"verb_lookups"}

VALID_METRICS = LLM_METRICS | TOP_LEVEL_METRICS


class ConsumptionService:
    def __init__(self, cols: dict):
        self.cols = cols

    def _today(self) -> str:
        """Returns today's UTC date as ISO string (e.g. '2026-02-19')."""
        return now_utc().date().isoformat()

    async def increment(
        self,
        user_id: Union[str, int],
        metric: str,
        uses_own_key: bool = False,
    ) -> None:
        """
        Increment a daily consumption counter for a user.

        If the stored consumption_date differs from today, resets all daily
        counters before incrementing (lazy daily reset).

        Args:
            user_id: Telegram user ID
            metric: One of 'cards_generated', 'stories_generated', 'verb_lookups'
            uses_own_key: If True, increments under user_api instead of system_api
                          (only applies to LLM metrics; verb_lookups is always top-level)
        """
        if metric not in VALID_METRICS:
            logger.warning(f"Unknown consumption metric: {metric}")
            return

        user_id_str = str(user_id)
        today = self._today()

        # Check if we need a daily reset
        user_doc = await self.cols["users"].find_one(
            {"user_id": user_id_str},
            {"consumption.consumption_date": 1},
        )

        stored_date = None
        if user_doc and "consumption" in user_doc:
            stored_date = user_doc["consumption"].get("consumption_date")

        if stored_date != today:
            # Reset all daily counters and set today's date
            await self.cols["users"].update_one(
                {"user_id": user_id_str},
                {
                    "$set": {
                        "consumption": UserConsumption(
                            consumption_date=today
                        ).model_dump()
                    }
                },
                upsert=True,
            )

        # Build the $inc path
        if metric in LLM_METRICS:
            api_bucket = "user_api" if uses_own_key else "system_api"
            # E.g. consumption.user_api.cards_generated
            inc_path = f"consumption.{api_bucket}.{metric}"
        else:
            # Top-level metric (verb_lookups)
            inc_path = f"consumption.{metric}"

        await self.cols["users"].update_one(
            {"user_id": user_id_str},
            {"$inc": {inc_path: 1}},
            upsert=True,
        )

        logger.debug(f"Consumption incremented: user={user_id_str} {inc_path}")

    async def get_consumption(self, user_id: Union[str, int]) -> UserConsumption:
        """
        Returns the current UserConsumption for a user.
        Auto-resets if the stored date is stale.
        """
        user_id_str = str(user_id)
        doc = await self.cols["users"].find_one(
            {"user_id": user_id_str},
            {"consumption": 1},
        )

        if not doc or "consumption" not in doc:
            return UserConsumption()

        consumption = UserConsumption.model_validate(doc["consumption"])

        # If date is stale, return fresh (don't bother writing back, next increment will reset)
        if consumption.consumption_date != self._today():
            return UserConsumption(consumption_date=self._today())

        return consumption
