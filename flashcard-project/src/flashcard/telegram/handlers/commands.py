from aiogram import Router, flags, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.enums import ChatAction

from flashcard.services.i18n import i18n
from flashcard.services.verb import VerbService
from flashcard.services.expression import ExpressionService
from flashcard.services.llm.llm import LLMService
from flashcard.telegram.ui.expression_lists import format_expression_list
from flashcard.telegram.ui.story import format_story_messages
from flashcard.telegram.ui.expression import format_review_message
from flashcard.telegram.keyboards import get_review_keyboard
from flashcard.utils.logger import get_logger
import random

logger = get_logger(__name__)
router = Router()

LANG_LEVEL = "A2-B1"
LANG_1_CODE = "en"
LANG_2_CODE = "fa"
LANG_1_LABEL = "🇬🇧 EN"
LANG_2_LABEL = "🇮🇷 FA"

@router.message(CommandStart())
async def cmd_start(message: Message):
    # Retrieve welcome message from I18n service
    welcome_text = i18n.get("commands.start.welcome")
    await message.answer(welcome_text)
    #TODO: translations and detailed explanations be added by buttons
    # also video, possibly in reply markup


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(i18n.get("commands.help.message"))
    await message.reply(i18n.get("commands.help.reply"))


@router.message(Command("get"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_get(message: Message, expression_service: ExpressionService, llm_service: LLMService):
    """
    Handle /get command to review a flashcard.
    """
    user_id = message.from_user.id
    
    # 1. Get review candidate
    candidate = await expression_service.get_review_candidate(user_id)
    
    if not candidate:
        # No cards to review
        # Using the message from n8n or similar intent
        await message.answer(i18n.get("commands.get.no_memory"))
        return

    # 2. Generate content (Definition, Translations, Example)
    try:
        # Using standard params as requested
        card = await llm_service.generate_expression_card(
            raw=candidate['value'],
            level=LANG_LEVEL,
            lang1_code=LANG_1_CODE,
            lang2_code=LANG_2_CODE,
            lang1_label=LANG_1_LABEL, 
            lang2_label=LANG_2_LABEL
        )
    except Exception as e:
        logger.error(f"Error generating card for {candidate['value']}: {e}")
    except Exception as e:
        logger.error(f"Error generating card for {candidate['value']}: {e}")
        await message.answer(i18n.get("commands.get.generation_error"))
        return

    # 3. Format Message
    text = format_review_message(card, candidate['value'])

    # 4. Keyboard
    keyboard = get_review_keyboard(str(candidate['_id']))
    
    # 5. Send & Update
    sent_msg = await message.answer(text, reply_markup=keyboard)
    
    # Update DB
    await expression_service.update_expression_sent(str(candidate['_id']), sent_msg.message_id)
    await expression_service.update_user_last_push(user_id)


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
    try:
        import_response = await llm_service.parse_import_list(command_args)
    except Exception as e:
        logger.error(f"LLM Import Error: {e}")
        await message.answer(i18n.get("commands.import.processing_error"))
        return

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


@router.message(Command("story"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_story(message: Message, llm_service: LLMService, expression_service: ExpressionService, logger_bot: Bot):
    msg_text = message.text or ""
    args = msg_text.split()[1:] # Ignore command
    
    # Defaults
    story_length = "6-10 sentences"
    
    # Check for -l flag
    if "-l" in args:
        story_length = "10-16 sentences"
        
    # Get user expressions
    expressions = await expression_service.get_all_expressions(message.from_user.id)
    
    if not expressions:
        await message.answer(i18n.get("commands.story.no_expressions", "No expressions found. Add some first!"))
        return

    # Select words (Shuffle & Limit to 80)
    # If <= 80, use all. If > 80, shuffle and take 80.
    selected_words = expressions
    if len(expressions) > 80:
        random.shuffle(expressions)
        selected_words = expressions[:80]
        
        random.shuffle(expressions)
        selected_words = expressions[:80]
        
    await message.answer(i18n.get("commands.story.writing", count=len(selected_words)))
        
    try:
        story_response = await llm_service.generate_story(
            words=selected_words, 
            target_lang="en", # Configurable in future
            story_length=story_length
        )
    except Exception as e:
        logger.error(f"Story generation error: {e}")
        await logger_bot.send_message(settings.ADMIN_ID, f"Story generation error for user {message.from_user.id}: {e}")
        await message.answer(i18n.get("commands.story.generation_error"))
        return

    # Send paragraphs
    messages = format_story_messages(story_response, target_lang="en")
    
    for text in messages:
        await message.answer(text)


@router.message(Command("verb"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_verb(message: Message, verb_service: VerbService):
    """
    Handle /verb command.
    """
    # 1. Extract verb
    extracted_verb = verb_service.extract_verb(message.text)
    
    if not extracted_verb:
        await message.answer(i18n.get("commands.verb.instruction"))
        return
    
    # 2. Validate verb format
    if not verb_service.is_valid_verb(extracted_verb):
        logger.warning(f"Invalid verb: {extracted_verb}")
        await message.answer(i18n.get("commands.verb.invalid"))
        return

    # 3. Get verb data (DB or API)
    # Give feedback to user that we are processing
    status_msg = await message.answer(i18n.get("commands.verb.searching", verb=extracted_verb))
    
    verb_data = await verb_service.get_verb_data(extracted_verb)
     
    if not verb_data:
        # Not found in DB or API, or API error
        error_text = i18n.get("commands.verb.api_error") # Or "not found" specific message
        await message.answer(error_text)
        return

    # Editing searching message
    # 4. Return success response
    from flashcard.telegram.ui.verb import format_verb_message
    from flashcard.telegram.keyboards import get_verb_keyboard
    
    formatted_text = format_verb_message(verb_data)
    keyboard = get_verb_keyboard(verb_data)
    
    await status_msg.edit_text(text=formatted_text, reply_markup=keyboard)


