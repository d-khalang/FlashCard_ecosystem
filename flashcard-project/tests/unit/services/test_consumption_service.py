import unittest
from datetime import date
from unittest.mock import MagicMock, AsyncMock, patch

from flashcard.services.consumption import ConsumptionService
from flashcard.schemas.user import UserConsumption


class TestConsumptionService(unittest.IsolatedAsyncioTestCase):
    def _make_service(self):
        mock_cols = {
            'users': MagicMock()
        }
        mock_cols['users'].find_one = AsyncMock(return_value=None)
        mock_cols['users'].update_one = AsyncMock(return_value=None)
        return ConsumptionService(mock_cols), mock_cols

    async def test_increment_new_user_cards_generated(self):
        """First increment for a new user should reset then inc system_api.cards_generated."""
        service, cols = self._make_service()
        # find_one returns None (new user) → triggers reset
        cols['users'].find_one = AsyncMock(return_value=None)

        await service.increment("123", "cards_generated")

        # Should have: 1 find_one + 2 update_one (reset + inc)
        self.assertEqual(cols['users'].update_one.call_count, 2)

        # First update_one = reset
        reset_call = cols['users'].update_one.call_args_list[0]
        reset_set = reset_call[0][1]["$set"]["consumption"]
        self.assertEqual(reset_set["consumption_date"], date.today().isoformat())
        self.assertEqual(reset_set["system_api"]["cards_generated"], 0)
        self.assertEqual(reset_set["user_api"]["cards_generated"], 0)

        # Second update_one = increment
        inc_call = cols['users'].update_one.call_args_list[1]
        self.assertEqual(inc_call[0][1]["$inc"], {"consumption.system_api.cards_generated": 1})

    async def test_increment_same_day_no_reset(self):
        """If consumption_date matches today, should NOT reset — just increment."""
        service, cols = self._make_service()
        today = date.today().isoformat()
        cols['users'].find_one = AsyncMock(return_value={
            "consumption": {"consumption_date": today}
        })

        await service.increment("123", "stories_generated")

        # Should have: 1 find_one + 1 update_one (inc only, no reset)
        self.assertEqual(cols['users'].update_one.call_count, 1)
        inc_call = cols['users'].update_one.call_args_list[0]
        self.assertEqual(inc_call[0][1]["$inc"], {"consumption.system_api.stories_generated": 1})

    async def test_increment_stale_date_triggers_reset(self):
        """If consumption_date is yesterday, should reset before incrementing."""
        service, cols = self._make_service()
        cols['users'].find_one = AsyncMock(return_value={
            "consumption": {"consumption_date": "2020-01-01"}
        })

        await service.increment("123", "cards_generated")

        # Should have: 1 find_one + 2 update_one (reset + inc)
        self.assertEqual(cols['users'].update_one.call_count, 2)

    async def test_increment_user_api_bucket(self):
        """When uses_own_key=True, should increment user_api path."""
        service, cols = self._make_service()
        today = date.today().isoformat()
        cols['users'].find_one = AsyncMock(return_value={
            "consumption": {"consumption_date": today}
        })

        await service.increment("123", "cards_generated", uses_own_key=True)

        inc_call = cols['users'].update_one.call_args_list[0]
        self.assertEqual(inc_call[0][1]["$inc"], {"consumption.user_api.cards_generated": 1})

    async def test_increment_verb_lookups_top_level(self):
        """verb_lookups should use top-level path, not nested under system_api."""
        service, cols = self._make_service()
        today = date.today().isoformat()
        cols['users'].find_one = AsyncMock(return_value={
            "consumption": {"consumption_date": today}
        })

        await service.increment("123", "verb_lookups")

        inc_call = cols['users'].update_one.call_args_list[0]
        self.assertEqual(inc_call[0][1]["$inc"], {"consumption.verb_lookups": 1})

    async def test_increment_invalid_metric_ignored(self):
        """Unknown metric should log warning and not touch DB."""
        service, cols = self._make_service()

        await service.increment("123", "nonexistent_metric")

        cols['users'].find_one.assert_not_called()
        cols['users'].update_one.assert_not_called()

    async def test_get_consumption_new_user(self):
        """Should return default UserConsumption for unknown user."""
        service, cols = self._make_service()
        cols['users'].find_one = AsyncMock(return_value=None)

        result = await service.get_consumption("999")
        self.assertIsInstance(result, UserConsumption)
        self.assertEqual(result.system_api.cards_generated, 0)

    async def test_get_consumption_stale_returns_fresh(self):
        """If stored date is old, get_consumption returns a fresh object."""
        service, cols = self._make_service()
        cols['users'].find_one = AsyncMock(return_value={
            "consumption": {
                "consumption_date": "2020-01-01",
                "system_api": {"cards_generated": 5, "stories_generated": 0},
                "user_api": {"cards_generated": 0, "stories_generated": 0},
                "verb_lookups": 2,
            }
        })

        result = await service.get_consumption("123")
        self.assertEqual(result.consumption_date, date.today().isoformat())
        self.assertEqual(result.system_api.cards_generated, 0)
        self.assertEqual(result.verb_lookups, 0)


if __name__ == '__main__':
    unittest.main()
