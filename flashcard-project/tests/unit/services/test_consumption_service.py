"""
Unit tests for flashcard.services.consumption.ConsumptionService

Tests the consumption tracking system: daily reset logic,
metric increment routing (system_api vs user_api vs top-level),
and the get_consumption query.
"""
from datetime import date
from unittest.mock import MagicMock, AsyncMock

from flashcard.services.consumption import ConsumptionService
from flashcard.schemas.user import UserConsumption


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_service(user_doc=None):
    """Create a ConsumptionService with mocked MongoDB."""
    mock_cols = {"users": MagicMock()}
    mock_cols["users"].find_one = AsyncMock(return_value=user_doc)
    mock_cols["users"].update_one = AsyncMock()
    return ConsumptionService(mock_cols), mock_cols


def _today_consumption(**overrides):
    """Returns a user doc with today's consumption date."""
    base = {"consumption": {"consumption_date": date.today().isoformat()}}
    base["consumption"].update(overrides)
    return base


# ===================================================================
# increment — daily reset logic
# ===================================================================
class TestIncrementResetLogic:

    async def test_new_user_triggers_reset_then_increment(self):
        """No user doc → reset counters to today's date → then increment."""
        service, cols = _make_service(user_doc=None)

        await service.increment("123", "cards_generated")

        # 2 update_one calls: reset + increment
        assert cols["users"].update_one.call_count == 2

        reset_call = cols["users"].update_one.call_args_list[0]
        reset_data = reset_call[0][1]["$set"]["consumption"]
        assert reset_data["consumption_date"] == date.today().isoformat()
        assert reset_data["system_api"]["cards_generated"] == 0

    async def test_stale_date_triggers_reset(self):
        """Stored date is old → reset before incrementing."""
        service, cols = _make_service(
            user_doc={"consumption": {"consumption_date": "2020-01-01"}}
        )

        await service.increment("123", "cards_generated")

        assert cols["users"].update_one.call_count == 2  # reset + inc

    async def test_same_day_skips_reset(self):
        """Today's date already stored → no reset, just increment."""
        service, cols = _make_service(user_doc=_today_consumption())

        await service.increment("123", "stories_generated")

        assert cols["users"].update_one.call_count == 1  # inc only
        inc_call = cols["users"].update_one.call_args_list[0]
        assert inc_call[0][1]["$inc"] == {
            "consumption.system_api.stories_generated": 1
        }


# ===================================================================
# increment — routing to correct bucket
# ===================================================================
class TestIncrementRouting:

    async def test_system_api_bucket_default(self):
        service, cols = _make_service(user_doc=_today_consumption())

        await service.increment("123", "cards_generated")

        inc = cols["users"].update_one.call_args[0][1]["$inc"]
        assert inc == {"consumption.system_api.cards_generated": 1}

    async def test_user_api_bucket_with_own_key(self):
        service, cols = _make_service(user_doc=_today_consumption())

        await service.increment("123", "cards_generated", uses_own_key=True)

        inc = cols["users"].update_one.call_args[0][1]["$inc"]
        assert inc == {"consumption.user_api.cards_generated": 1}

    async def test_verb_lookups_top_level(self):
        """verb_lookups lives at top level, not under system_api."""
        service, cols = _make_service(user_doc=_today_consumption())

        await service.increment("123", "verb_lookups")

        inc = cols["users"].update_one.call_args[0][1]["$inc"]
        assert inc == {"consumption.verb_lookups": 1}

    async def test_invalid_metric_ignored(self):
        """Unknown metric → warning logged, no DB writes."""
        service, cols = _make_service()

        await service.increment("123", "nonexistent_metric")

        cols["users"].find_one.assert_not_called()
        cols["users"].update_one.assert_not_called()


# ===================================================================
# get_consumption
# ===================================================================
class TestGetConsumption:

    async def test_new_user_returns_default(self):
        service, _ = _make_service(user_doc=None)

        result = await service.get_consumption("999")

        assert isinstance(result, UserConsumption)
        assert result.system_api.cards_generated == 0

    async def test_stale_date_returns_fresh_counters(self):
        """Old consumption_date → return zeroed-out object with today's date."""
        service, _ = _make_service(user_doc={
            "consumption": {
                "consumption_date": "2020-01-01",
                "system_api": {"cards_generated": 5, "stories_generated": 0},
                "user_api": {"cards_generated": 0, "stories_generated": 0},
                "verb_lookups": 2,
            }
        })

        result = await service.get_consumption("123")

        assert result.consumption_date == date.today().isoformat()
        assert result.system_api.cards_generated == 0
        assert result.verb_lookups == 0

    async def test_same_day_returns_stored_values(self):
        """Today's date → return stored counters as-is."""
        today = date.today().isoformat()
        service, _ = _make_service(user_doc={
            "consumption": {
                "consumption_date": today,
                "system_api": {"cards_generated": 3, "stories_generated": 1},
                "user_api": {"cards_generated": 0, "stories_generated": 0},
                "verb_lookups": 7,
            }
        })

        result = await service.get_consumption("123")

        assert result.consumption_date == today
        assert result.system_api.cards_generated == 3
        assert result.verb_lookups == 7
