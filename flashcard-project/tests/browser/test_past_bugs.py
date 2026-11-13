"""
Bugs that reached users, each pinned in a real browser engine. Every test here was checked to fail
with its fix removed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from playwright.async_api import expect

from tests.integration.harness import USER
from tests.integration.study_helpers import add_user, add_word, make_card


async def _start_study(page, button: str = "Study now"):
    await page.goto(page.base_url + "/")
    await page.get_by_role("button", name=button).click()


async def _opacity(page, selector: str) -> str:
    return await page.locator(selector).evaluate("element => getComputedStyle(element).opacity")


async def _settles_at(page, selector: str, opacity: str, timeout: float = 3.0) -> bool:
    """Whether the face's opacity reaches `opacity` within `timeout` seconds (the flip takes 0.5 s)."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if await _opacity(page, selector) == opacity:
            return True
        await asyncio.sleep(0.05)
    return False


async def test_v2_2_0_the_question_does_not_show_through_the_flipped_card(page, live):
    """iOS WebKit ignored backface-visibility on the scrolling card bodies, so the question showed
    through the answer, mirrored. The fix hides the turned-away face with opacity."""
    harness, _ = live
    await add_user(harness.cols, USER)
    await add_word(harness.cols, USER, "andare")
    await _start_study(page)
    await expect(page.locator(".face-front .q-word")).to_be_visible()
    assert await _opacity(page, ".face-back") == "0"

    await page.locator(".face-front .q-word").tap()

    await expect(page.get_by_role("button", name="Grade 4 of 5")).to_be_visible()
    assert await _settles_at(page, ".face-front", "0"), "the question is still visible behind the answer"
    assert await _settles_at(page, ".face-back", "1")


async def test_v2_3_1_grading_in_the_app_removes_the_bot_cards_buttons(page, live):
    """The bot's grade buttons stayed under a card already graded in the Mini App."""
    harness, _ = live
    await add_user(harness.cols, USER)
    await add_word(harness.cols, USER, "andare")
    await harness.send("/get")
    message_id = (await harness.cols["expression"].find_one({"value": "andare"}))["pending_message_id"]
    await _start_study(page, button="Continue your card")  # the bot's card is waiting

    await page.locator(".face-front .q-word").tap()
    await page.get_by_role("button", name="Grade 4 of 5").click()
    await expect(page.get_by_text("Session complete")).to_be_visible()
    await harness.idle()

    edits = harness.calls("EditMessageReplyMarkup")
    assert [(e["chat_id"], e["message_id"], e.get("reply_markup")) for e in edits] == [(USER, message_id, None)]


async def test_v2_1_0_out_of_credits_a_word_with_a_saved_card_is_still_studied(page, live):
    """At the limit, study stopped when the top word had no saved card, although another word had
    one that costs nothing to show."""
    from flashcard.utils.time import now_utc

    harness, _ = live
    await add_user(harness.cols, USER)
    # The top word: new, never reviewed, no saved card.
    await add_word(harness.cols, USER, "bene", age_days=30)
    # Well known and reviewed recently, so lower in priority, but with a saved card.
    await add_word(harness.cols, USER, "andare", age_days=1, reps=5, ewma_grade=4.5, success_streak=5, last_card={
        "card": make_card().model_dump(),
        "settings": {"level": "A2", "primary_language": "en", "secondary_language": None},
        "generated_at": datetime.now(timezone.utc) - timedelta(days=2),
    })
    await harness.cols["users"].update_one({"user_id": str(USER)}, {"$set": {
        "consumption.consumption_date": now_utc().date().isoformat(),
        "consumption.system_api.credits_used": 10_000}})

    await _start_study(page)

    await expect(page.locator(".face-front .q-word")).to_have_text("andare")
    await expect(page.locator(".face-front .badge")).to_have_text("Saved version")
    assert harness.llm.card_calls == 0
