"""
Unit tests for SettingsUseCases: validation and persistence of user settings, independent of Telegram.

Runs against a real UserService on the in-memory Mongo fake, because the allowed
values are enforced by UserService's setters.
"""
import pytest

from flashcard.app.settings import LEVELS, SettingsUseCases
from flashcard.schemas.user import MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, NO_LANGUAGE
from flashcard.services.user import UserService
from tests.integration.helpers import make_cols


def _use_cases(**user_fields):
    cols = make_cols(users=[{"user_id": "777", **user_fields}])
    return SettingsUseCases(user_service=UserService(cols=cols)), cols["users"].docs[0]


class TestLevel:

    @pytest.mark.parametrize("level", LEVELS)
    async def test_every_cefr_level_is_saved(self, level):
        use_cases, users = _use_cases()

        assert await use_cases.set_level(777, level) == level
        assert users["target_level"] == level

    @pytest.mark.parametrize("level", ["Z9", "a1", "", None])
    async def test_unknown_level_is_rejected(self, level):
        use_cases, users = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.set_level(777, level)
        assert set(users) == {"user_id"}  # nothing written


class TestInterval:

    @pytest.mark.parametrize("minutes", [MIN_INTERVAL_MINUTES, 45, MAX_INTERVAL_MINUTES])
    async def test_interval_in_range_is_saved(self, minutes):
        use_cases, users = _use_cases()

        assert await use_cases.set_interval(777, minutes) == minutes
        assert users["review_interval_minutes"] == minutes

    @pytest.mark.parametrize("minutes", [MIN_INTERVAL_MINUTES - 1, MAX_INTERVAL_MINUTES + 1, -5, 0, 30.0, "30",
                                         True, None])
    async def test_out_of_range_or_non_int_is_rejected(self, minutes):
        use_cases, users = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.set_interval(777, minutes)
        assert set(users) == {"user_id"}  # nothing written


class TestLanguages:

    @pytest.mark.parametrize("text, code", [("Farsi", "fa"), (" DE ", "de"), ("en", "en")])
    async def test_primary_accepts_names_and_codes(self, text, code):
        use_cases, users = _use_cases()

        assert await use_cases.set_primary_language(777, text) == code
        assert users["primary_language"] == code

    @pytest.mark.parametrize("text", ["none", "klingon", "", None])
    async def test_primary_rejects_none_unknown_and_non_text(self, text):
        use_cases, users = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.set_primary_language(777, text)
        assert set(users) == {"user_id"}  # nothing written

    @pytest.mark.parametrize("text, code", [("english", "en"), ("none", NO_LANGUAGE), ("No", NO_LANGUAGE)])
    async def test_secondary_accepts_languages_and_none(self, text, code):
        use_cases, users = _use_cases()

        assert await use_cases.set_secondary_language(777, text) == code
        assert users["secondary_language"] == code

    @pytest.mark.parametrize("text", ["klingon", None])
    async def test_secondary_rejects_unknown_and_non_text(self, text):
        use_cases, users = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.set_secondary_language(777, text)
        assert set(users) == {"user_id"}  # nothing written


class TestToggles:

    @pytest.mark.parametrize("current, new", [("standard", "dual"), ("dual", "standard")])
    async def test_review_mode_flips(self, current, new):
        use_cases, users = _use_cases(review_mode=current)

        assert await use_cases.toggle_review_mode(777) == new
        assert users["review_mode"] == new

    @pytest.mark.parametrize("current, wanted", [(True, False), (False, True), (True, True), (False, False)])
    async def test_set_active_is_idempotent(self, current, wanted):
        use_cases, users = _use_cases(is_active=current)

        assert await use_cases.set_active(777, wanted) is wanted
        assert users["is_active"] is wanted

    @pytest.mark.parametrize("mode", ["standard", "dual"])
    async def test_set_review_mode_is_idempotent(self, mode):
        use_cases, users = _use_cases(review_mode=mode)

        assert await use_cases.set_review_mode(777, mode) == mode
        assert users["review_mode"] == mode

    async def test_unknown_review_mode_is_rejected(self):
        use_cases, users = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.set_review_mode(777, "toggle")
        assert set(users) == {"user_id"}  # nothing written

    async def test_get_returns_the_user(self):
        use_cases, _ = _use_cases(target_level="B2")

        user = await use_cases.get(777)

        assert (user.user_id, user.target_level) == ("777", "B2")
