"""
Unit tests for the read-everything check against the in-memory Mongo fake.
"""
from flashcard.migrations.check_documents import check_documents
from flashcard.services.expression import ExpressionService
from flashcard.services.user import UserService
from tests.helpers import TEST_LANGUAGE
from tests.integration.helpers import make_cols


async def _run(cols):
    return await check_documents(cols, UserService(users=cols["users"], defaults=TEST_LANGUAGE.user_defaults))


async def test_readable_documents_report_nothing():
    cols = make_cols(
        users=[{"_id": "u", "user_id": "7", "last_reviewed_at": ""}],
        expressions=[{"_id": "e", "user_id": "7", "value": "ciao", "created_at": "2026-01-01T00:00:00Z"}],
    )

    report = await _run(cols)

    assert (report.users, report.expressions, report.unreadable) == (1, 1, 0)
    assert report.unreadable_ids == []


async def test_finds_what_convert_dates_cannot():
    cols = make_cols(users=[
        {"_id": "lang", "user_id": "1", "primary_language": "klingon"},
        {"_id": "active", "user_id": "2", "is_active": None},
        {"_id": "date", "user_id": "3", "created_at": 42},
        {"_id": "id", "user_id": 4.5},
    ])

    report = await _run(cols)

    assert report.unreadable == 4
    assert sorted(report.unreadable_ids) == ["users:active", "users:date", "users:id", "users:lang"]
    assert report.errors["users.is_active: bool_type"] == 1


async def test_spoiled_cards_are_reported_without_their_values():
    cols = make_cols(expressions=[
        {"_id": "empty", "user_id": "7", "value": ""},
        {"_id": "owner", "user_id": None, "value": "ciao"},
    ])

    report = await _run(cols)

    assert report.unreadable == 2
    assert report.errors["expression.value: string_too_short"] == 1
    assert report.errors["expression.user_id: string_type"] == 1
    assert "ciao" not in str(report)


async def test_stored_values_stay_out_of_the_logs(caplog):
    cols = make_cols(expressions=[{
        "_id": "e", "user_id": "7", "value": "ciao", "created_at": "2026-01-01T00:00:00Z",
        "last_card": {"card": {"success": True, "norm": "SECRETWORD"}, "settings": {}, "generated_at": "bad"},
    }, {"_id": "broken", "user_id": "7", "value": "", "note": "SECRETWORD"}])
    service = ExpressionService(expressions=cols["expression"])

    report = await _run(cols)
    await service.search_expressions(7, "ciao")

    assert report.unreadable == 1  # a stored card is only a fallback: dropped, not fatal
    assert "Unreadable stored card dropped" in caplog.text
    assert "SECRETWORD" not in caplog.text


async def test_writes_nothing():
    users = [{"_id": "u", "user_id": "7"}]
    cols = make_cols(users=users)

    await _run(cols)

    assert cols["users"].docs == users
