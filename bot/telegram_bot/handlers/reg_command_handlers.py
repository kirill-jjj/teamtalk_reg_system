"""This module handles commands for the registration flow."""
import logging

from aiogram import Bot as AiogramBot
from aiogram import Router, types
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db import is_telegram_id_registered
from ...core.db.crud import get_valid_deeplink_token, mark_deeplink_token_as_used
from ...core.localization import (
    get_available_languages_for_display,
    get_translator,
)
from ..schemas import RegistrationStateData
from ..states import RegistrationStates
from .reg_callback_data import LanguageCallback

logger = logging.getLogger(__name__)

command_router = Router()

def get_language_keyboard_builder() -> InlineKeyboardBuilder:
    """Helper to create the language selection keyboard."""
    builder = InlineKeyboardBuilder()
    available_langs = get_available_languages_for_display()
    if available_langs:
        for lang_info in available_langs:
            button_text = (
                lang_info['native_name']
                if lang_info['native_name']
                else lang_info['code'].upper()
            )
            builder.button(
                text=button_text,
                callback_data=LanguageCallback(
                    action="select", language_code=lang_info["code"]
                ),
            )
    else:  # Fallback if no languages are configured
        logger.error(
            "No languages discovered for Telegram language selection. "
            "Defaulting to English for keyboard."
        )
        builder.button(
            text="English",
            callback_data=LanguageCallback(action="select", language_code="en"),
        )
    return builder


async def _handle_deeplink_registration(
    message: types.Message,
    command_args: str,
    state: FSMContext,
    bot: AiogramBot,
    db_session: AsyncSession,
    telegram_id: int,
    initial_lang_code: str,
    state_data: RegistrationStateData,
) -> bool:
    """Handles deeplink registration logic."""
    _ = get_translator(initial_lang_code)
    if not settings.telegram_deeplink_registration_enabled:
        logger.info(
            "User %s attempted to use deeplink '%s' but feature is disabled.",
            telegram_id,
            command_args,
        )
        return False

    token_str = command_args
    deeplink_token = await get_valid_deeplink_token(db_session, token_str)

    if deeplink_token:
        logger.info(
            "User %s used valid deeplink token: %s", telegram_id, token_str
        )

        if await is_telegram_id_registered(db_session, telegram_id):
            await message.answer(
                _(
                    "You have already registered. This link cannot be used to "
                    "register again."
                )
            )
            await state.clear()
            return True

        await mark_deeplink_token_as_used(db_session, deeplink_token)
        state_data.is_deeplink_registration = True
        state_data.is_admin_registrar = False
        await state.set_data(state_data.model_dump())

        logger.info(
            "Deeplink registration started for user %s with token %s. "
            "Language set to %s.",
            telegram_id,
            token_str,
            initial_lang_code,
        )

        await state.set_state(RegistrationStates.choosing_language)
        await message.answer(
            _("Welcome! Please choose your language to continue registration."),
            reply_markup=get_language_keyboard_builder().as_markup(),
        )
        return True

    logger.warning(
        "User %s used invalid/expired/used deeplink token: %s",
        telegram_id,
        token_str,
    )
    await message.answer(
        _("This registration link is invalid, expired, or has already been used.")
    )
    await state.clear()
    return True


async def _handle_public_registration(
    message: types.Message,
    state: FSMContext,
    db_session: AsyncSession,
    telegram_id: int,
    initial_lang_code: str,
    state_data: RegistrationStateData,
) -> None:
    """Handles public registration logic."""
    _ = get_translator(initial_lang_code)

    if not settings.telegram_public_registration_enabled:
        logger.info(
            "User %s attempted public /start but feature is disabled. Ignoring.",
            telegram_id,
        )
        return

    state_data.is_admin_registrar = telegram_id in settings.admin_ids
    await state.set_data(state_data.model_dump())
    logger.info(
        "User %s starting public registration. Admin registrar: %s. "
        "Language set to %s.",
        telegram_id,
        state_data.is_admin_registrar,
        initial_lang_code,
    )

    if not state_data.is_admin_registrar and await is_telegram_id_registered(
        db_session, telegram_id
    ):
        await message.reply(
            _(
                "You have already registered one TeamTalk account from this "
                "Telegram account. Only one registration is allowed."
            )
        )
        await state.clear()
        return

    if settings.force_user_lang:
        forced_lang_code = settings.force_user_lang
        _f = get_translator(forced_lang_code)
        prompt_key = "Hello! Please enter a username for registration."
        translated_prompt = _f(prompt_key)

        if translated_prompt != prompt_key or forced_lang_code == "en":
            logger.info(
                "Forcing language to '%s' for user %s (public start) based on "
                "config.",
                forced_lang_code,
                telegram_id,
            )
            state_data.selected_language = forced_lang_code
            await state.set_data(state_data.model_dump())
            _ = _f
            await message.reply(_(prompt_key))
            await state.set_state(RegistrationStates.awaiting_username)
            return
        logger.warning(
            "FORCE_USER_LANG was set to '%s', but this language pack seems "
            "unavailable or incomplete. Proceeding with language selection for "
            "public start.",
            forced_lang_code,
        )

    await message.reply(
        _("Please choose your language:"),
        reply_markup=get_language_keyboard_builder().as_markup(),
    )
    await state.set_state(RegistrationStates.choosing_language)


@command_router.message(CommandStart())
async def start_command_handler(
    message: types.Message,
    command: CommandObject,
    state: FSMContext,
    bot: AiogramBot,
    db_session: AsyncSession,
) -> None:
    """Handles the /start command."""
    args = command.args
    user = message.from_user
    telegram_id = user.id

    initial_lang_code = (
        user.language_code
        if user.language_code and user.language_code.strip()
        else settings.bot_admin_lang
    )

    logger.info(
        "User %s initiated /start command. Args: '%s'",
        telegram_id,
        args if args else None,
    )

    state_data = RegistrationStateData(
        registrant_telegram_id=telegram_id, selected_language=initial_lang_code
    )

    if args and await _handle_deeplink_registration(
        message, args, state, bot, db_session, telegram_id,
        initial_lang_code, state_data
    ):
        return

    await _handle_public_registration(
        message, state, db_session, telegram_id, initial_lang_code, state_data
    )
