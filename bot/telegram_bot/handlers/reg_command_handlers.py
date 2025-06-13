import logging

from aiogram import Bot as AiogramBot
from aiogram import Router, types
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import config
from ...core.config import FORCE_USER_LANG
from ...core.db import is_telegram_id_registered
from ...core.db.crud import get_valid_deeplink_token, mark_deeplink_token_as_used
from ...core.localization import (
    get_admin_lang_code, # Used for messages before user lang is known or if user lang fails
    get_available_languages_for_display,
    get_translator,
)
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
            button_text = lang_info['native_name'] if lang_info['native_name'] else lang_info['code'].upper()
            builder.button(text=button_text, callback_data=LanguageCallback(action="select", language_code=lang_info['code']))
    else: # Fallback if no languages are configured
        logger.error("No languages discovered for Telegram language selection. Defaulting to English for keyboard.")
        builder.button(text="English", callback_data=LanguageCallback(action="select", language_code="en"))
    return builder

async def determine_user_language(telegram_id: int, state: FSMContext, db_session: AsyncSession) -> str:
    """Determines user language, falling back to Telegram's lang_code or admin default."""
    # This is a simplified version. A more robust version might query user preferences from DB.
    data = await state.get_data()
    user_lang_code = data.get("selected_language")
    if not user_lang_code:
        # If message.from_user is available here, use it, otherwise this needs to be passed or adapted
        # For now, using a generic approach. In start_command_handler, message.from_user is available.
        # This helper might be called from contexts where it's not.
        # Let's assume if no selected_language, we default to admin lang for now or a broad default.
        # In start_command_handler, message.from_user.language_code can be used before calling this.
        user_lang_code = config.CFG_ADMIN_LANG # Fallback, should be improved if user-specific preferred lang is available
        # logger.info(f"User language not in state for {telegram_id}, defaulting to {user_lang_code}.")
    return user_lang_code


@command_router.message(CommandStart())
async def start_command_handler(message: types.Message, command: CommandObject, state: FSMContext, bot: AiogramBot, db_session: AsyncSession):
    args = command.args
    user = message.from_user
    telegram_id = user.id

    # Initial language determination (can be refined)
    # Try message.from_user.language_code first if available and not empty
    initial_lang_code = user.language_code if user.language_code and user.language_code.strip() else config.CFG_ADMIN_LANG
    _ = get_translator(initial_lang_code) # Translator for initial messages

    logger.info(f"User {telegram_id} initiated /start command. Args: '{args if args else None}'")

    if args:  # A token is present in the /start command (deeplink)
        if not config.TELEGRAM_DEEPLINK_REGISTRATION_ENABLED:
            logger.info(f"User {telegram_id} attempted to use deeplink '{args}' but feature is disabled.")
            # According to requirements, no message to user if feature is disabled.
            return

        token_str = args
        deeplink_token = await get_valid_deeplink_token(db_session, token_str)

        if deeplink_token:
            logger.info(f"User {telegram_id} used valid deeplink token: {token_str}")

            # Check if already registered (even with deeplink, policy might be no re-registration)
            if await is_telegram_id_registered(db_session, telegram_id):
                await message.answer(_("You have already registered. This link cannot be used to register again."))
                await state.clear()
                return

            await mark_deeplink_token_as_used(db_session, deeplink_token)
            # Store that this is a deeplink registration and other necessary initial data
            await state.update_data(is_deeplink_registration=True,
                                    registrant_telegram_id=telegram_id,
                                    selected_language=initial_lang_code, # Store initial lang
                                    is_admin_registrar=False) # Deeplink users are not admins registering themselves

            logger.info(f"Deeplink registration started for user {telegram_id} with token {token_str}. Language set to {initial_lang_code}.")

            # Proceed to language selection or first registration step
            # For consistency, let's present language selection, even if initial_lang_code is set.
            # User can confirm or change.
            await state.set_state(RegistrationStates.choosing_language)
            await message.answer(_("Welcome! Please choose your language to continue registration."),
                                 reply_markup=get_language_keyboard_builder().as_markup())
            return
        else:  # Invalid, expired, or used token
            logger.warning(f"User {telegram_id} used invalid/expired/used deeplink token: {token_str}")
            await message.answer(_("This registration link is invalid, expired, or has already been used."))
            await state.clear()
            return

    # If no args, it's a direct /start command (public registration attempt)
    if not config.TELEGRAM_PUBLIC_REGISTRATION_ENABLED:
        logger.info(f"User {telegram_id} attempted public /start but feature is disabled. Ignoring.")
        # No response to the user, as per requirement (or a generic message if preferred)
        return

    # --- Original public /start logic follows here ---
    await state.update_data(is_deeplink_registration=False,
                            registrant_telegram_id=telegram_id,
                            selected_language=initial_lang_code) # Store initial lang

    # is_admin_registrar check
    is_admin_registrar = telegram_id in config.ADMIN_IDS_INT # Assuming ADMIN_IDS_INT is pre-calculated list of ints
    await state.update_data(is_admin_registrar=is_admin_registrar)
    logger.info(f"User {telegram_id} starting public registration. Admin registrar: {is_admin_registrar}. Language set to {initial_lang_code}.")


    if not is_admin_registrar and await is_telegram_id_registered(db_session, telegram_id):
        await message.reply(
            _("You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed.")
        )
        await state.clear()
        return

    # Language selection / forced language logic for public /start
    if FORCE_USER_LANG and FORCE_USER_LANG.strip():
        forced_lang_code = FORCE_USER_LANG.strip()
        _f = get_translator(forced_lang_code)
        # Using a neutral key for the "enter username" prompt that can be translated.
        prompt_key = "Hello! Please enter a username for registration."
        translated_prompt = _f(prompt_key)

        if translated_prompt != prompt_key or forced_lang_code == "en": # Check if translation occurred
            logger.info(f"Forcing language to '{forced_lang_code}' for user {telegram_id} (public start) based on config.")
            await state.update_data(selected_language=forced_lang_code) # Update state with forced lang
            _ = _f # Use the forced language translator for this message
            await message.reply(_(prompt_key)) # Send translated prompt
            await state.set_state(RegistrationStates.awaiting_username)
            return
        else:
            logger.warning(
                f"FORCE_USER_LANG was set to '{forced_lang_code}', but this language pack seems unavailable or incomplete. Proceeding with language selection for public start."
            )
            # Fall through to language selection if forced lang is bad

    # If language is not forced or forced language is invalid, proceed with selection (public /start)
    # Use the initially determined language for the prompt message itself
    await message.reply(_("Please choose your language:"),
                        reply_markup=get_language_keyboard_builder().as_markup())
    await state.set_state(RegistrationStates.choosing_language)


logger.info("Registration command handlers configured with CommandStart and deeplink logic.")
