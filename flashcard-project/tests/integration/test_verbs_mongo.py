"""
The Verbs page over a real MongoDB (docs/verbs/contract.md section 5): the practice upsert and its
indexes, and the capped recent-verbs list, through the bot and the Mini App together.
"""
from pymongo.errors import DuplicateKeyError

import pytest

from flashcard.schemas.user import stored_user_id
from tests.verb_fixtures import load

from .harness import USER


async def test_lookups_from_the_bot_and_the_app_share_the_recent_list(harness):
    await harness.send("/verb vado")
    response = await harness.get("/verbs/lookup?q=andare")
    home = await harness.get("/verbs/home")

    assert response.json()["status"] == "found"
    assert home.json()["recent"] == ["andare"]
    user = await harness.cols["users"].find_one({"user_id": stored_user_id(USER)})
    assert user["verbs_recent"] == ["andare"] and user["consumption"]["verb_lookups"] == 2


async def test_recent_verbs_are_capped_at_10_on_mongo(harness):
    await harness.get("/me")  # creates the user
    users = harness.cols["users"]
    await users.update_one({"user_id": stored_user_id(USER)},
                           {"$set": {"verbs_recent": [f"v{i}" for i in range(9)] + ["andare"]}})

    await harness.get("/verbs/lookup?q=vado")

    user = await users.find_one({"user_id": stored_user_id(USER)})
    assert user["verbs_recent"] == ["andare"] + [f"v{i}" for i in range(9)]


async def test_a_stored_null_recent_list_is_replaced(harness):
    await harness.get("/me")  # creates the user
    users = harness.cols["users"]
    await users.update_one({"user_id": stored_user_id(USER)}, {"$set": {"verbs_recent": None}})

    await harness.get("/verbs/lookup?q=vado")

    user = await users.find_one({"user_id": stored_user_id(USER)})
    assert user["verbs_recent"] == ["andare"]


async def test_practice_upserts_one_document_per_user_and_verb(harness):
    body = load("miniapp/practice-request.json")

    first = await harness.post("/verbs/practice", body)
    second = await harness.post("/verbs/practice", {**body, "score": 6, "missed": []})
    other = await harness.post("/verbs/practice", {**body, "tense_id": "indicativo-presente", "score": 1,
                                                   "missed": ["1s"]})

    assert (first.status_code, second.status_code, other.status_code) == (204, 204, 204)
    docs = [doc async for doc in harness.cols["verb_practice"].find({})]
    assert len(docs) == 1
    tenses = docs[0]["tenses"]
    assert tenses["indicativo-futuro_semplice"] | {"last_at": None} == {
        "attempts": 2, "last_score": 6, "best_score": 6, "out_of": 6, "missed": [], "last_at": None}
    assert tenses["indicativo-presente"]["attempts"] == 1
    assert docs[0]["updated_at"] >= tenses["indicativo-futuro_semplice"]["last_at"]


async def test_practice_indexes(harness):
    indexes = await harness.cols["verb_practice"].index_information()
    keys = {tuple(info["key"]): info.get("unique", False) for info in indexes.values()}

    assert keys[(("user_id", 1), ("infinitive", 1))] is True
    assert (("user_id", 1), ("updated_at", 1)) in keys
    await harness.cols["verb_practice"].insert_one({"user_id": "1", "infinitive": "andare"})
    with pytest.raises(DuplicateKeyError):
        await harness.cols["verb_practice"].insert_one({"user_id": "1", "infinitive": "andare"})


async def test_the_old_cache_is_never_touched(harness):
    await harness.send("/verb andare")
    await harness.get("/verbs/andare/drill/indicativo-presente")

    db = harness.cols["users"].database
    assert "conjugation" not in await db.list_collection_names()


async def test_the_card_is_found_with_the_card_index_collation(harness):
    await harness.get("/me")
    await harness.cols["expression"].insert_many([
        {"user_id": stored_user_id(USER), "value": "Andare", "status": "active"},
        {"user_id": stored_user_id(USER), "value": "fàre", "status": "active"},
    ])

    andare = (await harness.get("/verbs/lookup?q=andare")).json()
    # A card that differs by an accent is another word (the unique index says so too).
    core = harness.app.state.core
    fare = await core.expression_service.find_word(USER, "fare")

    assert andare["in_collection"] is True and fare is None
