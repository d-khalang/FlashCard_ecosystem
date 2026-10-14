"""
Tests for /list_my_flashcards at the Telegram entry point: saved values -> ordered, formatted deck.

Flags: -p plain (no letter headings), -t creation order (oldest first); combinable as -pt / -tp.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.collection import CollectionUseCases
from flashcard.services.i18n import i18n
from flashcard.telegram.handlers import collection
from flashcard.telegram.ui.expression_lists import format_expression_list


USER_ID = 555


def _deps(values=None):
    expression_service = MagicMock()
    expression_service.get_all_expressions = AsyncMock(
        side_effect=lambda user_id, sort_by_time=False: list(values or []))
    return SimpleNamespace(expression_service=expression_service)


def _use_cases(d) -> CollectionUseCases:
    return CollectionUseCases(review_state=AsyncMock(), expression_service=d.expression_service, user_service=MagicMock(),
                              consumption_service=MagicMock(), llm_service=MagicMock())


async def _run(d, text="/list_my_flashcards"):
    message = MagicMock()
    message.text = text
    message.from_user.id = USER_ID
    message.answer = AsyncMock()
    await collection.cmd_list_my_flashcards(message, collection_use_cases=_use_cases(d))
    return message


def _sent(message) -> list[str]:
    return [call.args[0] for call in message.answer.await_args_list]


class TestListOrder:

    async def test_default_is_alphabetical_with_letter_headings(self):
        message = await _run(_deps(["fare", "Andare", "bere"]))

        sent = _sent(message)
        assert sent == format_expression_list(["Andare", "bere", "fare"])
        assert "<b>A</b>" in sent[0] and "<b>F</b>" in sent[0]
        assert sent[0].index("Andare") < sent[0].index("bere") < sent[0].index("fare")

    async def test_default_loads_unsorted_values(self):
        d = _deps(["fare"])
        await _run(d)

        d.expression_service.get_all_expressions.assert_awaited_once_with(USER_ID, sort_by_time=False)

    @pytest.mark.parametrize("text", ["/list_my_flashcards -t", "/list_my_flashcards -pt", "/list_my_flashcards -tp",
                                      "/list_my_flashcards -p -t"])
    async def test_t_flag_keeps_creation_order(self, text):
        d = _deps(["fare", "andare", "bere"])
        message = await _run(d, text=text)

        d.expression_service.get_all_expressions.assert_awaited_once_with(USER_ID, sort_by_time=True)
        sent = _sent(message)
        assert sent[0].index("fare") < sent[0].index("andare") < sent[0].index("bere")
        assert "<b>A</b>" not in sent[0]


class TestListFormat:

    async def test_p_flag_is_plain_alphabetical_without_headings(self):
        message = await _run(_deps(["fare", "andare"]), text="/list_my_flashcards -p")

        assert _sent(message) == format_expression_list(["andare", "fare"], plain=True)
        assert "<b>A</b>" not in _sent(message)[0]

    async def test_header_counts_items(self):
        message = await _run(_deps(["fare", "andare"]))

        assert _sent(message)[0].startswith(i18n.get("messages.collection.header", count=2))

    async def test_empty_deck_shows_empty_message(self):
        message = await _run(_deps([]))

        assert _sent(message) == [i18n.get("messages.collection.empty")]

    async def test_long_deck_is_split_into_several_messages(self):
        values = [f"parola{i:04d} " + "x" * 40 for i in range(200)]
        message = await _run(_deps(values))

        sent = _sent(message)
        assert len(sent) == 3
        assert all(len(chunk) <= 4096 for chunk in sent)

    @pytest.mark.parametrize("flags", ["", " -p", " -t", " -pt"])
    @pytest.mark.parametrize("count, width", [(200, 40), (1000, 5), (90, 120)])
    async def test_every_item_is_sent_exactly_once_across_splits(self, flags, count, width):
        # Varied first letters, so letter headings also fall on chunk boundaries.
        values = [f"{'abcdefghij'[i % 10]}parola{i:04d} " + "x" * width for i in range(count)]
        message = await _run(_deps(values), text="/list_my_flashcards" + flags)

        sent = _sent(message)
        assert len(sent) > 1
        assert all(len(chunk) <= 4096 for chunk in sent)
        sent_lines = [line for chunk in sent for line in chunk.splitlines() if "parola" in line]
        expected = values if "t" in flags else sorted(values, key=str.lower)
        assert sent_lines == expected


class TestListArguments:

    @pytest.mark.parametrize("text", ["/list_my_flashcards p t", "/list_my_flashcards --", "/list_my_flashcards"])
    async def test_without_dash_flags_uses_defaults(self, text):
        d = _deps(["fare"])
        await _run(d, text=text)

        d.expression_service.get_all_expressions.assert_awaited_once_with(USER_ID, sort_by_time=False)

    async def test_known_quirk_any_dash_word_containing_t_enables_time_order(self):
        # Any argument starting with "-" is scanned for the letters p and t, e.g. "-xyzt".
        d = _deps(["fare"])
        await _run(d, text="/list_my_flashcards -xyzt")

        d.expression_service.get_all_expressions.assert_awaited_once_with(USER_ID, sort_by_time=True)

    async def test_bot_mention_does_not_hide_flags(self):
        d = _deps(["fare"])
        await _run(d, text="/list_my_flashcards@kartino_bot -t")

        d.expression_service.get_all_expressions.assert_awaited_once_with(USER_ID, sort_by_time=True)
