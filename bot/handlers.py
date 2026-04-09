from __future__ import annotations

import logging

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from bot.api_client import BackendClient
from bot.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Доступные команды:\n"
    "/start - регистрация и запуск бота\n"
    "/help - показать помощь\n\n"
    "Кнопки меню пока работают как заглушки для базового интерфейса."
)


def _backend_client_from_context(context: ContextTypes.DEFAULT_TYPE) -> BackendClient:
    return context.application.bot_data["backend_client"]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    user = update.effective_user
    backend_client = _backend_client_from_context(context)

    try:
        registration = await backend_client.register_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
    except httpx.HTTPError as error:
        logger.exception("Registration request failed: %s", error)
        await update.message.reply_text(
            "Сервис регистрации сейчас недоступен. Попробуйте еще раз чуть позже."
        )
        return

    if registration.created:
        greeting = (
            f"Привет, {user.first_name or 'друг'}!\n"
            f"Ты зарегистрирован. Твой Telegram ID: {registration.telegram_id}"
        )
    else:
        greeting = (
            f"С возвращением, {user.first_name or 'друг'}!\n"
            f"Ты уже зарегистрирован. Telegram ID: {registration.telegram_id}"
        )

    await update.message.reply_text(
        greeting,
        reply_markup=main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(HELP_TEXT)


async def menu_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    text = update.message.text.strip()
    if text == "📝 Моя анкета":
        await update.message.reply_text("Раздел анкеты будет добавлен на следующем этапе.")
        return
    if text == "❤️ Смотреть анкеты":
        await update.message.reply_text("Просмотр анкет будет добавлен на следующем этапе.")
        return
    if text == "ℹ️ Помощь":
        await update.message.reply_text(HELP_TEXT)
        return

    await update.message.reply_text(
        "Пока поддерживаются команды /start, /help и кнопки базового меню."
    )
