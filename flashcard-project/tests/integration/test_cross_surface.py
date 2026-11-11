"""
One card, two surfaces: what the user does in the Mini App shows up in the bot chat, and the
other way round. Runs the real bot dispatcher and the real API in one process (see harness.py).
"""
from __future__ import annotations

from flashcard.telegram.ui.factories.grade_callback import GradeCallback

from .harness import USER
from .study_helpers import add_user, add_word


async def _bot_card(harness) -> tuple[str, int]:
    """A word sent for review by the bot, with its grade buttons: (expression id, message id)."""
    await add_user(harness.cols, USER)
    expression_id = await add_word(harness.cols, USER, "andare")
    await harness.send("/get")
    card = await harness.cols["expression"].find_one({"value": "andare"})
    assert _grade_buttons(harness), "the bot sent no card with grade buttons"
    return expression_id, card["pending_message_id"]


def _grade_buttons(harness) -> dict[int, str]:
    """The grade buttons under the last card the bot sent, as {grade: callback data}."""
    for payload in reversed(harness.calls("SendMessage")):
        rows = payload.get("reply_markup", {}).get("inline_keyboard", [])
        buttons = {}
        for button in (button for row in rows for button in row):
            data = button.get("callback_data", "")
            if data.startswith(GradeCallback.__prefix__ + ":"):
                buttons[GradeCallback.unpack(data).grade] = data
        if buttons:
            return buttons
    return {}


async def _app_card(harness) -> dict:
    response = await harness.get("/study/current")
    assert response.status_code == 200
    return response.json()["card"]


async def test_the_app_shows_the_card_the_bot_sent(harness):
    expression_id, message_id = await _bot_card(harness)

    card = await _app_card(harness)

    assert (card["expression_id"], card["delivery_id"]) == (expression_id, message_id)


async def test_grading_in_the_app_removes_the_bot_cards_buttons(harness):
    """v2.3.1: the buttons stayed under a card already graded in the app."""
    _, message_id = await _bot_card(harness)
    card = await _app_card(harness)

    graded = await harness.post("/study/grade", {"delivery_id": card["delivery_id"], "grade": 4,
                                                 "expression_id": card["expression_id"],
                                                 "direction": card["direction"]})
    await harness.idle()

    assert graded.status_code == 200
    edits = harness.calls("EditMessageReplyMarkup")
    assert [(e["chat_id"], e["message_id"], e.get("reply_markup")) for e in edits] == [(USER, message_id, None)]


async def test_undo_in_the_app_puts_the_buttons_back(harness):
    _, message_id = await _bot_card(harness)
    card = await _app_card(harness)
    await harness.post("/study/grade", {"delivery_id": card["delivery_id"], "grade": 4,
                                        "expression_id": card["expression_id"], "direction": card["direction"]})

    undone = await harness.post("/study/undo")
    await harness.idle()

    assert undone.status_code == 200
    last = harness.calls("EditMessageReplyMarkup")[-1]
    assert last["message_id"] == message_id and "inline_keyboard" in last["reply_markup"]


async def test_a_button_left_behind_does_not_grade_twice(harness):
    expression_id, message_id = await _bot_card(harness)
    card = await _app_card(harness)
    await harness.post("/study/grade", {"delivery_id": card["delivery_id"], "grade": 4,
                                        "expression_id": card["expression_id"], "direction": card["direction"]})
    await harness.idle()
    before = await harness.cols["expression"].find_one({"value": "andare"})

    await harness.tap(min(_grade_buttons(harness).items())[1], message_id)

    after = await harness.cols["expression"].find_one({"value": "andare"})
    assert {k: v for k, v in after.items() if k != "_id"} == {k: v for k, v in before.items() if k != "_id"}
    assert harness.calls("AnswerCallbackQuery"), "the tap got no answer"


async def test_grading_in_the_bot_leaves_nothing_to_grade_in_the_app(harness):
    expression_id, message_id = await _bot_card(harness)
    card = await _app_card(harness)

    await harness.tap(max(_grade_buttons(harness).items())[1], message_id)
    graded = await harness.post("/study/grade", {"delivery_id": card["delivery_id"], "grade": 4,
                                                 "expression_id": card["expression_id"],
                                                 "direction": card["direction"]})

    assert graded.json() == {"status": "not_pending"}
