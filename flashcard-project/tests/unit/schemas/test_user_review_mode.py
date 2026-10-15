"""
UserDB.review_mode: reading is forgiving (unknown → "standard"), so one bad stored
value cannot break the scheduler or a user's commands. Writes stay strict.
"""
import pytest

from flashcard.schemas.user import UserDB


@pytest.mark.parametrize("mode", ["standard", "dual"])
def test_known_modes_are_kept(mode):
    assert UserDB(user_id="1", review_mode=mode).review_mode == mode


@pytest.mark.parametrize("stored", ["weird", "Dual", "", None, 3])
def test_unknown_stored_value_reads_as_standard(stored, caplog):
    assert UserDB.model_validate({"user_id": "1", "review_mode": stored}).review_mode == "standard"
    assert "Unknown stored review_mode" in caplog.text


def test_missing_mode_defaults_to_standard():
    assert UserDB(user_id="1").review_mode == "standard"
