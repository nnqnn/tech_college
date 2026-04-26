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


def profile_menu_keyboard(has_profile: bool) -> ReplyKeyboardMarkup:
    rows = [["✏️ Заполнить заново"]]
    if has_profile:
        rows.append(["🗑 Удалить анкету"])
    rows.append(["⬅️ В меню"])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
    )


def gender_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            ["Мужской", "Женский"],
            ["Другое"],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def gender_preference_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            ["Мужской", "Женский"],
            ["Любой"],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def profile_action_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            ["👍 Лайк", "👎 Пропуск"],
            ["📝 Моя анкета", "❤️ Смотреть анкеты"],
            ["ℹ️ Помощь"],
        ],
        resize_keyboard=True,
    )
