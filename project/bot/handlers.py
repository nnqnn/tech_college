from __future__ import annotations

import logging
import re

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from bot.api_client import BackendClient, ProfileResult
from bot.keyboards import (
    gender_keyboard,
    gender_preference_keyboard,
    main_menu_keyboard,
    profile_action_keyboard,
    profile_menu_keyboard,
)

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Доступные команды:\n"
    "/start - регистрация и запуск бота\n"
    "/help - показать помощь\n\n"
    "Через меню можно заполнить анкету, смотреть анкеты, ставить лайк или пропуск."
)

PROFILE_FLOW_KEY = "profile_flow"
CURRENT_PROFILE_KEY = "current_profile_id"
SKIP_VALUES = {"любой", "любая", "все", "неважно", "нет", "-", "any", "all"}


class ProfileInputError(ValueError):
    pass


def _parse_age(value: str) -> int:
    age = int(value.strip())
    if age < 18 or age > 120:
        raise ProfileInputError("Возраст должен быть от 18 до 120.")
    return age


def _parse_text(value: str) -> str:
    text = value.strip()
    if not text:
        raise ProfileInputError("Значение не должно быть пустым.")
    return text


def _parse_optional_text(value: str) -> str | None:
    text = value.strip()
    if text.lower() in SKIP_VALUES:
        return None
    return _parse_text(text)


def _parse_age_range(value: str) -> tuple[int, int]:
    numbers = [int(item) for item in re.findall(r"\d+", value)]
    if len(numbers) != 2:
        raise ProfileInputError("Введите диапазон в формате 18-35.")
    age_min, age_max = numbers
    if age_min < 18 or age_max > 120 or age_min > age_max:
        raise ProfileInputError("Диапазон должен быть от 18 до 120, минимум не больше максимума.")
    return age_min, age_max


def _parse_photos_count(value: str) -> int:
    photos_count = int(value.strip())
    if photos_count < 0 or photos_count > 20:
        raise ProfileInputError("Количество фото должно быть от 0 до 20.")
    return photos_count


PROFILE_STEPS: tuple[dict[str, object], ...] = (
    {
        "key": "age",
        "prompt": "Сколько тебе лет?",
        "parser": _parse_age,
    },
    {
        "key": "gender",
        "prompt": "Укажи пол.",
        "parser": _parse_text,
        "keyboard": "gender",
    },
    {
        "key": "city",
        "prompt": "Из какого ты города?",
        "parser": _parse_text,
    },
    {
        "key": "interests",
        "prompt": "Напиши интересы через запятую.",
        "parser": _parse_text,
    },
    {
        "key": "age_range",
        "prompt": "Какой возрастной диапазон интересен? Например: 18-35",
        "parser": _parse_age_range,
    },
    {
        "key": "gender_pref",
        "prompt": "Какой пол хочешь видеть? Можно написать 'любой'.",
        "parser": _parse_optional_text,
        "keyboard": "gender_pref",
    },
    {
        "key": "city_pref",
        "prompt": "Какой город предпочитаешь? Можно написать 'любой'.",
        "parser": _parse_optional_text,
    },
    {
        "key": "photos_count",
        "prompt": "Сколько фото будет в анкете? Напиши число.",
        "parser": _parse_photos_count,
    },
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
    if PROFILE_FLOW_KEY in context.user_data:
        await _handle_profile_step(update, context, text)
        return

    if text == "📝 Моя анкета":
        await _show_my_profile(update, context)
        return
    if text == "✏️ Заполнить заново":
        await _start_profile_flow(update, context)
        return
    if text == "🗑 Удалить анкету":
        await _delete_my_profile(update, context)
        return
    if text == "⬅️ В меню":
        context.user_data.pop(PROFILE_FLOW_KEY, None)
        context.user_data.pop(CURRENT_PROFILE_KEY, None)
        await update.message.reply_text("Главное меню.", reply_markup=main_menu_keyboard())
        return
    if text == "❤️ Смотреть анкеты":
        await _show_next_profile(update, context)
        return
    if text == "👍 Лайк":
        await _handle_profile_action(update, context, is_like=True)
        return
    if text == "👎 Пропуск":
        await _handle_profile_action(update, context, is_like=False)
        return
    if text == "ℹ️ Помощь":
        await update.message.reply_text(HELP_TEXT)
        return

    await update.message.reply_text(
        "Используй кнопки меню или команды /start и /help.",
        reply_markup=main_menu_keyboard(),
    )


async def _start_profile_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    context.user_data[PROFILE_FLOW_KEY] = {"step": 0, "data": {}}
    await _send_profile_step_prompt(update, int(0))


async def _handle_profile_step(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    if update.message is None or update.effective_user is None:
        return

    flow = context.user_data[PROFILE_FLOW_KEY]
    step_index = int(flow["step"])
    data = flow["data"]
    step = PROFILE_STEPS[step_index]
    parser = step["parser"]

    try:
        parsed = parser(text)  # type: ignore[operator]
    except (ValueError, ProfileInputError) as error:
        await update.message.reply_text(str(error) or "Не получилось разобрать ответ.")
        return

    if step["key"] == "age_range":
        age_min, age_max = parsed
        data["age_pref_min"] = age_min
        data["age_pref_max"] = age_max
    else:
        data[step["key"]] = parsed

    next_step_index = step_index + 1
    if next_step_index < len(PROFILE_STEPS):
        flow["step"] = next_step_index
        await _send_profile_step_prompt(update, next_step_index)
        return

    backend_client = _backend_client_from_context(context)
    try:
        profile = await backend_client.upsert_profile(update.effective_user.id, data)
    except httpx.HTTPError as error:
        logger.exception("Profile save failed: %s", error)
        await update.message.reply_text(
            "Не удалось сохранить анкету. Попробуй еще раз чуть позже.",
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.pop(PROFILE_FLOW_KEY, None)
        return

    context.user_data.pop(PROFILE_FLOW_KEY, None)
    await update.message.reply_text(
        (
            "Анкета сохранена.\n"
            f"Заполненность: {profile.profile_completion_pct}%\n"
            "Теперь можно смотреть анкеты."
        ),
        reply_markup=main_menu_keyboard(),
    )


async def _show_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    backend_client = _backend_client_from_context(context)
    try:
        profile = await backend_client.get_profile(update.effective_user.id)
    except httpx.HTTPError as error:
        logger.exception("Profile request failed: %s", error)
        await update.message.reply_text(
            "Не удалось получить анкету. Попробуй еще раз чуть позже.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if profile is None:
        await update.message.reply_text(
            "Анкета пока не заполнена.",
            reply_markup=profile_menu_keyboard(has_profile=False),
        )
        return

    await update.message.reply_text(
        "Твоя анкета:\n\n" + _format_profile(profile),
        reply_markup=profile_menu_keyboard(has_profile=True),
    )


async def _delete_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    backend_client = _backend_client_from_context(context)
    try:
        await backend_client.delete_profile(update.effective_user.id)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            await update.message.reply_text(
                "Анкеты для удаления пока нет.",
                reply_markup=profile_menu_keyboard(has_profile=False),
            )
            return
        logger.exception("Profile delete failed: %s", error)
        await update.message.reply_text(
            "Не удалось удалить анкету.",
            reply_markup=main_menu_keyboard(),
        )
        return
    except httpx.HTTPError as error:
        logger.exception("Profile delete failed: %s", error)
        await update.message.reply_text(
            "Сервис анкет сейчас недоступен.",
            reply_markup=main_menu_keyboard(),
        )
        return

    context.user_data.pop(CURRENT_PROFILE_KEY, None)
    await update.message.reply_text(
        "Анкета удалена. Ее можно заполнить заново.",
        reply_markup=profile_menu_keyboard(has_profile=False),
    )


async def _show_next_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    backend_client = _backend_client_from_context(context)
    try:
        profile = await backend_client.get_next_profile(update.effective_user.id)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 400:
            await update.message.reply_text(
                "Сначала заполни свою анкету.",
                reply_markup=main_menu_keyboard(),
            )
            return
        logger.exception("Feed request failed: %s", error)
        await update.message.reply_text(
            "Не удалось получить анкету. Попробуй позже.",
            reply_markup=main_menu_keyboard(),
        )
        return
    except httpx.HTTPError as error:
        logger.exception("Feed request failed: %s", error)
        await update.message.reply_text(
            "Сервис просмотра сейчас недоступен.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if profile is None:
        context.user_data.pop(CURRENT_PROFILE_KEY, None)
        await update.message.reply_text(
            "Подходящих анкет пока нет.",
            reply_markup=main_menu_keyboard(),
        )
        return

    context.user_data[CURRENT_PROFILE_KEY] = profile.telegram_id
    await update.message.reply_text(
        _format_profile(profile),
        reply_markup=profile_action_keyboard(),
    )


async def _handle_profile_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    is_like: bool,
) -> None:
    if update.message is None or update.effective_user is None:
        return

    current_profile_id = context.user_data.get(CURRENT_PROFILE_KEY)
    if current_profile_id is None:
        await update.message.reply_text(
            "Сначала открой анкету для просмотра.",
            reply_markup=main_menu_keyboard(),
        )
        return

    backend_client = _backend_client_from_context(context)
    try:
        interaction = await backend_client.create_interaction(
            requester_telegram_id=update.effective_user.id,
            responder_telegram_id=int(current_profile_id),
            is_like=is_like,
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 409:
            await update.message.reply_text("Эта анкета уже оценена.")
            context.user_data.pop(CURRENT_PROFILE_KEY, None)
            await _show_next_profile(update, context)
            return
        logger.exception("Interaction request failed: %s", error)
        await update.message.reply_text(
            "Не удалось сохранить оценку.",
            reply_markup=main_menu_keyboard(),
        )
        return
    except httpx.HTTPError as error:
        logger.exception("Interaction request failed: %s", error)
        await update.message.reply_text(
            "Сервис оценок сейчас недоступен.",
            reply_markup=main_menu_keyboard(),
        )
        return

    context.user_data.pop(CURRENT_PROFILE_KEY, None)
    if interaction.match:
        await update.message.reply_text("Есть взаимный лайк. Можно начинать общение.")
    await _show_next_profile(update, context)


def _format_profile(profile: ProfileResult) -> str:
    score_line = ""
    if profile.total_score is not None:
        score_line = f"\nРейтинг: {profile.total_score:.1f}"

    return (
        f"Анкета #{profile.telegram_id}\n"
        f"Возраст: {profile.age}\n"
        f"Пол: {profile.gender}\n"
        f"Город: {profile.city}\n"
        f"Интересы: {profile.interests}\n"
        f"Фото: {profile.photos_count}"
        f"{score_line}"
    )


async def _send_profile_step_prompt(update: Update, step_index: int) -> None:
    if update.message is None:
        return

    step = PROFILE_STEPS[step_index]
    keyboard_name = step.get("keyboard")
    reply_markup = None
    if keyboard_name == "gender":
        reply_markup = gender_keyboard()
    elif keyboard_name == "gender_pref":
        reply_markup = gender_preference_keyboard()

    await update.message.reply_text(
        str(step["prompt"]),
        reply_markup=reply_markup,
    )
