from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton, 
                           ReplyKeyboardMarkup, KeyboardButton)

from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

def get_explanation_keyboard(card_id: str = "temp_id") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Save", callback_data=f"save:{card_id}")
    builder.button(text="Regen", callback_data=f"regen:{card_id}")
    return builder.as_markup()

def get_reply_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Test1")
    builder.button(text="Test2")
    return builder.as_markup()