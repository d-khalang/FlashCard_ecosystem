from aiogram import Router, flags
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from aiogram.enums import ChatAction

from flashcard.app.collection import (
    AllDuplicates, CollectionUseCases, Imported, InvalidLanguage, NothingFound, ParseFailed, TooLong,
)
from flashcard.app.quota import QuotaExceeded
from flashcard.services.i18n import i18n
from flashcard.telegram.ui.expression_lists import format_expression_list
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()


@router.message(Command("remove"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_remove(message: Message):
    bot_username = getattr(message.bot, "username", None)
    inline_name = f"@{bot_username}" if bot_username else "@italian_assist_bot"
    await message.answer(
        i18n.get("commands.remove.guide", inline_name=inline_name)
    )


@router.message(Command("import"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_import(message: Message, command: CommandObject, collection_use_cases: CollectionUseCases):
    # aiogram strips the command and any @botname; args is None when empty or whitespace.
    if not command.args:
        await message.answer(i18n.get("commands.import.usage_guide"))
        return

    result = await collection_use_cases.import_items(message.from_user.id, command.args)

    if isinstance(result, Imported):
        await message.answer(i18n.get(
            "commands.import.success", count=len(result.items), items_str="\n".join(result.items)))
    elif isinstance(result, AllDuplicates):
        await message.answer(i18n.get("commands.import.all_duplicates"))
    elif isinstance(result, ParseFailed):
        await message.answer(i18n.get("commands.import.import_failed", log_msg=result.log or "Unknown error."))
    elif isinstance(result, NothingFound):
        await message.answer(i18n.get("commands.import.no_items_found"))
    elif isinstance(result, InvalidLanguage):
        await message.answer(i18n.get("messages.errors.invalid_learning_language_input"))
    elif isinstance(result, TooLong):
        await message.answer(i18n.get("commands.import.too_long", limit=result.limit))
    elif isinstance(result, QuotaExceeded):
        await message.answer(i18n.get(
            "messages.errors.quota_exceeded", type="card", tier=result.tier, limit=result.limit))


@router.message(Command("list_my_flashcards"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_list_my_flashcards(message: Message, collection_use_cases: CollectionUseCases):
    # Flags: -p plain list, -t creation order; combinable as -pt, -tp or -p -t.
    plain = sort_by_time = False
    for arg in (message.text or "").split()[1:]:
        if arg.startswith("-"):
            plain = plain or "p" in arg
            sort_by_time = sort_by_time or "t" in arg

    order = "created" if sort_by_time else "alphabetical"
    values = await collection_use_cases.list_items(message.from_user.id, order=order)

    # Letter headings only make sense for an alphabetical list.
    for msg in format_expression_list(values, plain=plain, sort_alphabetical=order == "alphabetical"):
        await message.answer(msg)
