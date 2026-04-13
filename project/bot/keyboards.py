from __future__ import annotations

from telegram import ReplyKeyboardMarkup


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            ["📝 Моя анкета", "❤️ Смотреть анкеты"],
            ["ℹ️ Помощь"],
        ],
        resize_keyboard=True,
    )
