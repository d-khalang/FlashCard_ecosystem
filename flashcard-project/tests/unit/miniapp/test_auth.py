"""
Mini App sign-in: the HMAC check of Telegram's initData.
"""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode

import pytest

from flashcard.miniapp.auth import InitDataError, MAX_AGE_SECONDS, validate_init_data
from tests.integration.study_helpers import BOT_TOKEN, sign_init_data


def _check(raw: str, **kwargs):
    return validate_init_data(raw, bot_token=kwargs.pop("bot_token", BOT_TOKEN), now=kwargs.pop("now", None) or datetime.now(timezone.utc), **kwargs)


class TestValidInitData:

    def test_returns_the_signed_user_id_and_username(self):
        identity = _check(sign_init_data(42, username="noor"))

        assert (identity.user_id, identity.username) == (42, "noor")

    def test_a_user_without_a_username(self):
        raw = sign_init_data(0, user=json.dumps({"id": 7, "first_name": "T"}))

        assert _check(raw).username is None

    def test_accepts_data_just_inside_the_24_hour_limit(self):
        assert _check(sign_init_data(42, auth_age_seconds=MAX_AGE_SECONDS - 60)).user_id == 42

    def test_the_signature_field_is_part_of_the_signed_text(self):
        assert _check(sign_init_data(42, extra={"signature": "abc", "chat_type": "private"})).user_id == 42


class TestRejected:

    def test_a_signature_made_with_another_bot_token(self):
        with pytest.raises(InitDataError):
            _check(sign_init_data(42, bot_token="999:other"))

    def test_a_changed_hash(self):
        raw = sign_init_data(42)
        fields = dict(parse_qsl(raw))
        fields["hash"] = ("0" if fields["hash"][0] != "0" else "1") + fields["hash"][1:]

        with pytest.raises(InitDataError):
            _check(urlencode(fields))

    def test_a_tampered_user_keeps_the_old_hash(self):
        fields = dict(parse_qsl(sign_init_data(42)))
        fields["user"] = json.dumps({"id": 1, "first_name": "T"}, separators=(",", ":"))

        with pytest.raises(InitDataError):
            _check(urlencode(fields))

    def test_a_tampered_auth_date_keeps_the_old_hash(self):
        fields = dict(parse_qsl(sign_init_data(42, auth_age_seconds=MAX_AGE_SECONDS + 600)))
        fields["auth_date"] = str(int(datetime.now(timezone.utc).timestamp()))

        with pytest.raises(InitDataError):
            _check(urlencode(fields))

    def test_auth_date_older_than_24_hours(self):
        with pytest.raises(InitDataError, match="age"):
            _check(sign_init_data(42, auth_age_seconds=MAX_AGE_SECONDS + 60))

    def test_auth_date_in_the_future(self):
        with pytest.raises(InitDataError, match="age"):
            _check(sign_init_data(42, auth_age_seconds=-3600))

    def test_no_hash(self):
        fields = dict(parse_qsl(sign_init_data(42)))
        del fields["hash"]

        with pytest.raises(InitDataError):
            _check(urlencode(fields))

    def test_a_repeated_field(self):
        with pytest.raises(InitDataError):
            _check(sign_init_data(42) + "&query_id=again")

    @pytest.mark.parametrize("raw", ["", "garbage", "a=b", "hash=" + "0" * 64, "x" * 20000, "a=%zz"])
    def test_malformed_data(self, raw):
        with pytest.raises(InitDataError):
            _check(raw)

    @pytest.mark.parametrize("user", [
        '{"id": "42"}', '{"id": 0}', '{"id": -5}', '{"id": true}', '{"id": 1.5}', '[1]', '"x"', 'not json',
        '{"id": 1, "id": 2}', '{"id": NaN}', '{"id": 5, "username": 7}',
    ])
    def test_a_signed_user_that_is_not_a_valid_user(self, user):
        with pytest.raises(InitDataError):
            _check(sign_init_data(0, user=user))

    def test_the_error_never_contains_the_data(self):
        raw = sign_init_data(424242, bot_token="999:other")

        with pytest.raises(InitDataError) as error:
            _check(raw)

        assert "424242" not in str(error.value) and raw not in str(error.value)

    def test_a_naive_clock_is_a_programming_error(self):
        with pytest.raises(ValueError):
            validate_init_data(sign_init_data(42), bot_token=BOT_TOKEN, now=datetime.now())
