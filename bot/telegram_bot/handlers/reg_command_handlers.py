import logging

from aiogram import Bot as AiogramBot
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import config
from ...core.config import FORCE_USER_LANG
from ...core.db import is_telegram_id_registered
from ...core.localization import (
    get_admin_lang_code,
    get_available_languages_for_display,
    get_translator,
)
from ..states import RegistrationStates
from .reg_callback_data import LanguageCallback

logger = logging.getLogger(__name__)

command_router = Router()

@command_router.message(Command("start"))
async def start_command_handler(message: types.Message, state: FSMContext, bot: AiogramBot, db_session: AsyncSession):
    telegram_id = message.from_user.id
    # Default to admin lang for initial messages, can be updated later if user selects a language
    _ = get_translator(get_admin_lang_code())

    # Check if the registrar is an admin
    is_admin_registrar = telegram_id in config.ADMIN_IDS
    # Store who is initiating and whether they are an admin.
    # Also storing 'registrant_telegram_id' which is the user being registered (same as initiator here at /start)
    await state.update_data(registrant_telegram_id=telegram_id, is_admin_registrar=is_admin_registrar)
    logger.info(f"User {telegram_id} starting registration process. Admin registrar: {is_admin_registrar}")

    # If user is not an admin and is already registered, stop them.
    if not is_admin_registrar and await is_telegram_id_registered(db_session, telegram_id):
        await message.reply(
            _("You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed.")
        )
        await state.clear()
        return

    # Language selection / forced language logic starts here
    if FORCE_USER_LANG and FORCE_USER_LANG.strip():
        forced_lang_code = FORCE_USER_LANG.strip()
        _f = get_translator(forced_lang_code)
        original_key = "Hello! Please enter a username for registration." # Key for translation
        translated_string = _f(original_key)

        # Check if translation exists and is different from the key, or if the forced lang is 'en'
        if translated_string != original_key or forced_lang_code == "en":
            logger.info(f"Forcing language to '{forced_lang_code}' for user {telegram_id} based on config.")
            await state.update_data(selected_language=forced_lang_code)
            await message.reply(_f(original_key))
            await state.set_state(RegistrationStates.awaiting_username)
            return
        else:
            logger.warning(
                f"FORCE_USER_LANG was set to '{forced_lang_code}', but this language pack seems unavailable or incomplete. Proceeding with language selection."
            )

    # If language is not forced or forced language is invalid, proceed with selection
    _en = get_translator("en") # Default translator for this specific message
    available_langs = get_available_languages_for_display()
    builder = InlineKeyboardBuilder()
    if available_langs:
        for lang_info in available_langs:
            button_text = lang_info['native_name'] if lang_info['native_name'] else lang_info['code'].upper()
            # Using LanguageCallback from reg_callback_data.py, action="select"
            builder.button(text=button_text, callback_data=LanguageCallback(action="select", language_code=lang_info['code']))
    else: # Fallback if no languages are configured
        logger.error("No languages discovered for Telegram language selection. Defaulting to English.")
        builder.button(text="English", callback_data=LanguageCallback(action="select", language_code="en"))

    await message.reply(_en("Please choose your language:"), reply_markup=builder.as_markup())
    # The state will be updated by the language_selection_handler in reg_callback_handlers.py
    await state.set_state(RegistrationStates.choosing_language)

logger.info("Registration command handlers configured.")
