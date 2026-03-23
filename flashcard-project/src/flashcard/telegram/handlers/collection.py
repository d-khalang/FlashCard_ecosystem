from aiogram import Router, flags
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ChatAction

from flashcard.services.expression import ExpressionService
from flashcard.services.llm.llm import LLMService
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
async def cmd_import(message: Message, llm_service: LLMService, expression_service: ExpressionService):
    msg_text = message.text or ""
    # Remove command itself to get arguments
    command_args = msg_text[7:] if len(msg_text) >= 7 else ""
    
    if not command_args:
        await message.answer(i18n.get("commands.import.usage_guide"))
        return

    # Parse with LLM
    import_response = await llm_service.parse_import_list(command_args)

    if not import_response.success:
        log_msg = import_response.log or "Unknown error."
        await message.answer(i18n.get("commands.import.import_failed", log_msg=log_msg))
        return

    if not import_response.import_list:
         await message.answer(i18n.get("commands.import.no_items_found"))
         return

    # Bulk Insert
    inserted_items = await expression_service.add_expressions_bulk(message.from_user.id, import_response.import_list)
    
    if inserted_items:
        count = len(inserted_items)
        items_str = "\n".join(inserted_items)
        await message.answer(i18n.get("commands.import.success", count=count, items_str=items_str))
    else:
        await message.answer(i18n.get("commands.import.all_duplicates"))


@router.message(Command("list_my_flashcards"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_list_my_flashcards(message: Message, expression_service: ExpressionService):
    msg_text = message.text or ""
    # Parse arguments
    # Supports -p, -t, or -pt, -tp, or -p -t etc.
    args = msg_text.split()
    
    plain = False
    sort_by_time = False
    
    for arg in args[1:]: # Skip command itself
        if arg.startswith("-"):
            if "p" in arg:
                plain = True
            if "t" in arg:
                sort_by_time = True
    
    # Logic:
    # -t -> sort_by_time=True in service
    # -p -> plain=True in UI
    # -t also means sort_alphabetical=False in UI (implied by getting time-sorted list from DB)
    
    expressions = await expression_service.get_all_expressions(message.from_user.id, sort_by_time=sort_by_time)
    
    # If sorted by time, we disable UI alphabetical sort to preserve DB order
    sort_alphabetical = not sort_by_time
    
    messages = format_expression_list(expressions, plain=plain, sort_alphabetical=sort_alphabetical)
    
    for msg in messages:
        await message.answer(msg)

