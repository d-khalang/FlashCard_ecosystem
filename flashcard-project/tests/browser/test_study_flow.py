"""Studying in the built Mini App, tapped through like a user on an iPhone (WebKit) and an Android phone."""
from __future__ import annotations

from playwright.async_api import expect

from tests.integration.harness import USER
from tests.integration.study_helpers import add_user, add_word


async def _open(page):
    await page.goto(page.base_url + "/")
    await expect(page.get_by_role("button", name="Study now")).to_be_visible()


async def test_a_word_is_revealed_graded_and_undone(page, live):
    harness, _ = live
    await add_user(harness.cols, USER)
    await add_word(harness.cols, USER, "andare")
    await _open(page)

    await page.get_by_role("button", name="Study now").click()
    await expect(page.locator(".face-front .q-word")).to_have_text("andare")
    await page.locator(".face-front .q-word").tap()  # what a user taps
    await page.get_by_role("button", name="Grade 4 of 5").click()

    await expect(page.get_by_text("Session complete")).to_be_visible()
    await expect(page.get_by_role("status").filter(has_text="1 reviewed")).to_be_visible()
    stored = await harness.cols["expression"].find_one({"value": "andare"})
    assert stored["last_grade"] == 4

    await page.get_by_role("button", name="Undo").click()
    await expect(page.get_by_role("button", name="Grade 4 of 5")).to_be_visible()
    stored = await harness.cols["expression"].find_one({"value": "andare"})
    assert stored.get("last_grade", 0) == 0


# --- Edge states ---------------------------------------------------------------------------------

async def _used_up_credits(harness):
    from flashcard.utils.time import now_utc
    await harness.cols["users"].update_one({"user_id": str(USER)}, {"$set": {
        "consumption.consumption_date": now_utc().date().isoformat(),
        "consumption.system_api.credits_used": 10_000}})


async def test_a_new_user_is_invited_to_add_words(page, live):
    harness, _ = live
    await add_user(harness.cols, USER)

    await page.goto(page.base_url + "/")

    await expect(page.get_by_text("No words yet")).to_be_visible()


async def test_out_of_credits_with_no_stored_card_says_so(page, live):
    harness, _ = live
    await add_user(harness.cols, USER)
    await add_word(harness.cols, USER, "andare")
    await _used_up_credits(harness)
    await _open(page)

    await page.get_by_role("button", name="Study now").click()

    await expect(page.get_by_text("Out of credits")).to_be_visible()
    assert harness.llm.card_calls == 0


async def test_a_failed_grade_says_so_and_can_be_retried(page, live):
    harness, _ = live
    await add_user(harness.cols, USER)
    await add_word(harness.cols, USER, "andare")
    await _open(page)
    await page.get_by_role("button", name="Study now").click()
    await page.locator(".face-front .q-word").tap()

    async def fail(route):
        await route.fulfill(status=500, content_type="application/json",
                            body='{"error": {"code": "internal", "message": "boom"}}')

    await page.route("**/api/v1/study/grade", fail)
    await page.get_by_role("button", name="Grade 4 of 5").click()
    await expect(page.get_by_role("alert")).to_contain_text("Could not save your answer")
    assert (await harness.cols["expression"].find_one({"value": "andare"})).get("last_grade", 0) == 0

    await page.unroute("**/api/v1/study/grade")
    await page.get_by_role("button", name="Grade 4 of 5").click()
    await expect(page.get_by_text("Session complete")).to_be_visible()
    assert (await harness.cols["expression"].find_one({"value": "andare"}))["last_grade"] == 4
