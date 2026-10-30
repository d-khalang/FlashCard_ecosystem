"""One user id type in code (int), one stored form (decimal text), converted only by the owners."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.schemas.user import UserDB, parse_stored_user_id, stored_user_id
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.review_state import ReviewStateStore
from flashcard.services.user import UserService
from tests.helpers import TEST_LANGUAGE, make_user


class TestStoredForm:

    def test_int_is_stored_as_decimal_text(self):
        assert stored_user_id(42) == "42"

    @pytest.mark.parametrize("value", [0, -1])
    def test_ids_below_one_are_rejected(self, value):
        with pytest.raises(ValueError):
            stored_user_id(value)

    @pytest.mark.parametrize("value", ["42", 42.0, True, None])
    def test_anything_but_an_int_is_rejected(self, value):
        with pytest.raises(TypeError):
            stored_user_id(value)

    @pytest.mark.parametrize("value, expected", [
        ("42", 42), ("007", None), ("0", None), (42, None), ("abc", None), ("4 2", None), ("", None),
        ("-1", None), ("٤٢", None),
    ])
    def test_parse_accepts_only_the_form_stored_user_id_writes(self, value, expected):
        assert parse_stored_user_id(value) == expected

    @pytest.mark.parametrize("user_id", [1, 7, 42, 2**53])
    def test_round_trip(self, user_id):
        assert parse_stored_user_id(stored_user_id(user_id)) == user_id


class TestUserDB:

    def test_reads_the_stored_text_as_int(self):
        assert make_user(user_id="42").user_id == 42

    def test_dump_is_the_stored_form(self):
        """A dump round-trips through storage."""
        user = make_user(user_id=42)
        assert user.model_dump()["user_id"] == "42"
        assert UserDB.model_validate(user.model_dump()).user_id == 42

    @pytest.mark.parametrize("value", ["abc", "", "007", "-1", 0, -1, 4.2, None])
    def test_a_bad_stored_id_makes_the_document_unreadable(self, value):
        with pytest.raises(ValueError):
            make_user(user_id=value)


class TestOwnersRejectTextIds:
    """A text id from a caller fails loudly instead of matching nothing."""

    @pytest.mark.parametrize("call", [
        lambda col: UserService(col, defaults=TEST_LANGUAGE.user_defaults).get_user("42"),
        lambda col: ConsumptionService(col).increment("42", "cards_generated"),
        lambda col: ExpressionService(col).get_all_expressions("42"),
        lambda col: ReviewStateStore(col).clear_pending("42"),
    ])
    async def test_text_id_raises(self, call):
        col = MagicMock()
        col.find_one = AsyncMock(return_value=None)
        col.update_one = AsyncMock()
        with pytest.raises(TypeError):
            await call(col)
        col.update_one.assert_not_awaited()
