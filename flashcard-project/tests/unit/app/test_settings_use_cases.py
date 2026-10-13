"""
Unit tests for SettingsUseCases: validation and persistence of user settings, independent of Telegram.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.settings import (
    LEVELS, MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, NO_LANGUAGE, SettingsUseCases,
)
from flashcard.schemas.user import UserDB


def _use_cases(user=None, *, new_status=True):
    users = MagicMock()
    users.get_user = AsyncMock(return_value=user or UserDB(user_id="777"))
    users.update_setting = AsyncMock()
    users.toggle_active_status = AsyncMock(return_value=new_status)
    return SettingsUseCases(user_service=users), users


class TestLevel:

    @pytest.mark.parametrize("level", LEVELS)
    async def test_every_cefr_level_is_saved(self, level):
        use_cases, users = _use_cases()

        assert await use_cases.set_level(777, level) == level
        users.update_setting.assert_awaited_once_with(777, "target_level", level)

    @pytest.mark.parametrize("level", ["Z9", "a1", "", None])
    async def test_unknown_level_is_rejected(self, level):
        use_cases, users = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.set_level(777, level)
        users.update_setting.assert_not_awaited()


class TestInterval:

    @pytest.mark.parametrize("minutes", [MIN_INTERVAL_MINUTES, 45, MAX_INTERVAL_MINUTES])
    async def test_interval_in_range_is_saved(self, minutes):
        use_cases, users = _use_cases()

        assert await use_cases.set_interval(777, minutes) == minutes
        users.update_setting.assert_awaited_once_with(777, "review_interval_minutes", minutes)

    @pytest.mark.parametrize("minutes", [MIN_INTERVAL_MINUTES - 1, MAX_INTERVAL_MINUTES + 1, -5, 0, 30.0, "30",
                                         True, None])
    async def test_out_of_range_or_non_int_is_rejected(self, minutes):
        use_cases, users = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.set_interval(777, minutes)
        users.update_setting.assert_not_awaited()


class TestLanguages:

    @pytest.mark.parametrize("text, code", [("Farsi", "fa"), (" DE ", "de"), ("en", "en")])
    async def test_primary_accepts_names_and_codes(self, text, code):
        use_cases, users = _use_cases()

        assert await use_cases.set_primary_language(777, text) == code
        users.update_setting.assert_awaited_once_with(777, "primary_language", code)

    @pytest.mark.parametrize("text", ["none", "klingon", "", None])
    async def test_primary_rejects_none_unknown_and_non_text(self, text):
        use_cases, users = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.set_primary_language(777, text)
        users.update_setting.assert_not_awaited()

    @pytest.mark.parametrize("text, code", [("english", "en"), ("none", NO_LANGUAGE), ("No", NO_LANGUAGE)])
    async def test_secondary_accepts_languages_and_none(self, text, code):
        use_cases, users = _use_cases()

        assert await use_cases.set_secondary_language(777, text) == code
        users.update_setting.assert_awaited_once_with(777, "secondary_language", code)

    @pytest.mark.parametrize("text", ["klingon", None])
    async def test_secondary_rejects_unknown_and_non_text(self, text):
        use_cases, users = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.set_secondary_language(777, text)
        users.update_setting.assert_not_awaited()


class TestToggles:

    @pytest.mark.parametrize("current, new", [("standard", "dual"), ("dual", "standard")])
    async def test_review_mode_flips(self, current, new):
        use_cases, users = _use_cases(UserDB(user_id="777", review_mode=current))

        assert await use_cases.toggle_review_mode(777) == new
        users.update_setting.assert_awaited_once_with(777, "review_mode", new)

    @pytest.mark.parametrize("new_status", [True, False])
    async def test_active_returns_new_status(self, new_status):
        use_cases, users = _use_cases(new_status=new_status)

        assert await use_cases.toggle_active(777) is new_status
        users.toggle_active_status.assert_awaited_once_with(777)

    async def test_get_returns_the_user(self):
        user = UserDB(user_id="777", target_level="B2")
        use_cases, _ = _use_cases(user)

        assert await use_cases.get(777) == user
