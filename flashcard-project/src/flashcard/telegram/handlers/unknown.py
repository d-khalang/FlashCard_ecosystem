from aiogram import Router, F
from aiogram.types import Message

from flashcard.services.i18n import i18n

router = Router()


# Unknown commands - must be registered AFTER all domain command routers
@router.message(F.text.startswith("/"))
async def cmd_unknown(message: Message):
    """
    Handle unknown commands.
    """
    await message.answer(i18n.get("commands.unknown.message"))
