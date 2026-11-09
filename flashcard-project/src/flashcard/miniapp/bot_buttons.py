"""
Keep the grade buttons of a bot-delivered card in step with what happens to it in the app.

A card the bot sent has its Telegram message id as delivery id (positive; the app's own are
negative). Grading it in the app removes the buttons from that message, and undoing the grade
puts them back.

This is cosmetic, so it runs after the response and a failure is only logged: the grade is what
counts, and a tap on a button left behind answers "already graded" and removes them (the bot's
`handle_grade`). Calls for one user run in the order they were asked for, so a quick grade and
undo always end with the buttons back.
"""
import asyncio
from typing import Awaitable, Callable

from aiogram import Bot

from flashcard.app.study import StudyCard
from flashcard.schemas.user import UserId
from flashcard.services.i18n import I18nService
from flashcard.telegram.keyboards import get_review_keyboard
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 10
# How long shutdown waits for calls in flight; a call it gives up on just leaves the old buttons.
CLOSE_TIMEOUT_SECONDS = 5.0


class BotCardButtons:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._tasks: set[asyncio.Task] = set()
        self._last: dict[UserId, asyncio.Task] = {}

    def remove(self, user_id: UserId, delivery_id: int) -> None:
        """The card delivered as `delivery_id` was graded in the app."""
        if delivery_id > 0:
            self._start(user_id, lambda: self._set_markup(user_id, delivery_id, None))

    def restore(self, user_id: UserId, card: StudyCard, i18n: I18nService) -> None:
        """A grade made in the app was undone, so `card` is waiting for a grade again."""
        if card.delivery_id > 0:
            keyboard = get_review_keyboard(i18n, card.expression_id, direction=card.direction)
            self._start(user_id, lambda: self._set_markup(user_id, card.delivery_id, keyboard))

    async def close(self) -> None:
        """Give calls in flight a moment to finish, cancel the rest and close the session."""
        tasks = list(self._tasks)
        if tasks:
            _, unfinished = await asyncio.wait(tasks, timeout=CLOSE_TIMEOUT_SECONDS)
            for task in unfinished:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.bot.session.close()

    def _start(self, user_id: UserId, call: Callable[[], Awaitable[object]]) -> None:
        task = asyncio.create_task(self._run(self._last.get(user_id), call), name=f"bot-buttons-{user_id}")
        self._tasks.add(task)
        self._last[user_id] = task

        def forget(done: asyncio.Task) -> None:
            self._tasks.discard(done)
            if self._last.get(user_id) is done:
                del self._last[user_id]

        task.add_done_callback(forget)

    @staticmethod
    async def _run(previous: asyncio.Task | None, call: Callable[[], Awaitable[object]]) -> None:
        if previous is not None:
            await asyncio.wait([previous])
        try:
            await call()
        except Exception as e:
            logger.warning(f"Could not update the buttons of a bot card: {e}")

    async def _set_markup(self, user_id: UserId, message_id: int, markup) -> None:
        await self.bot.edit_message_reply_markup(
            # The bot sends cards to the user's private chat, whose id is the user's.
            chat_id=user_id,
            message_id=message_id,
            reply_markup=markup,
            request_timeout=REQUEST_TIMEOUT_SECONDS,
        )
