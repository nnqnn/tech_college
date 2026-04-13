from __future__ import annotations

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.api_client import BackendClient
from bot.config import load_settings
from bot.handlers import help_command, menu_message_handler, start_command


def configure_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )


def main() -> None:
    configure_logging()
    settings = load_settings()

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["backend_client"] = BackendClient(settings.backend_api_url)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message_handler))

    application.run_polling()


if __name__ == "__main__":
    main()
