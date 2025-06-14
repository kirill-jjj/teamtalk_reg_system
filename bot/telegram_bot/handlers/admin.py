import logging
import secrets
from datetime import datetime, timedelta

import logging # Ensure logging is imported if not already at the top
from aiogram import types, Bot as AiogramBot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext # Added import
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import config
from ...core.db.crud import create_deeplink_token, get_user_by_identifier, delete_telegram_registration # Added CRUD imports
from ...core.localization import get_translator, get_admin_lang_code
from ..keyboards.admin_keyboards import get_admin_panel_keyboard, CALLBACK_DATA_DELETE_USER
from ..states import AdminActions

logger = logging.getLogger(__name__)

router = Router()

# Localization Keys (replacing old placeholders)
KEY_ADMIN_PANEL_TITLE = "admin_panel_title"
KEY_PROMPT_USER_IDENTIFIER_FOR_DELETION = "admin_delete_prompt_identifier"
KEY_PROCESSING_DELETE_REQUEST = "admin_delete_processing"
KEY_USER_DELETED_SUCCESSFULLY = "admin_delete_success"
KEY_FAILED_TO_DELETE_USER = "admin_delete_fail_db"
KEY_USER_NOT_FOUND = "admin_delete_user_not_found"
KEY_INVALID_INPUT_FOR_DELETION = "admin_delete_invalid_input"


@router.message(Command("adminpanel"))
async def admin_panel_handler(message: types.Message):
    # Admin check
    admin_ids_int = []
    if config.ADMIN_IDS:
        for admin_id_str in config.ADMIN_IDS:
            try:
                admin_ids_int.append(int(admin_id_str))
            except ValueError:
                logger.warning(f"Invalid admin ID in config: {admin_id_str}. Skipping.")

    if message.from_user.id not in admin_ids_int:
        logger.warning(f"User {message.from_user.id} (not an admin) tried to use /adminpanel.")
        return

    # For now, using a simple string. Localization can be added later.
    admin_lang = get_admin_lang_code() # This would be needed for localization
    _ = get_translator(admin_lang)
    reply_text = _(KEY_ADMIN_PANEL_TITLE) # Using simple string for now

    keyboard = get_admin_panel_keyboard()
    await message.reply(reply_text, reply_markup=keyboard)


@router.callback_query(F.data == CALLBACK_DATA_DELETE_USER)
async def delete_user_start_handler(callback_query: types.CallbackQuery, state: FSMContext):
    # Admin check (important for callback queries too)
    admin_ids_int = []
    if config.ADMIN_IDS:
        for admin_id_str in config.ADMIN_IDS:
            try:
                admin_ids_int.append(int(admin_id_str))
            except ValueError:
                logger.warning(f"Invalid admin ID in config for callback: {admin_id_str}. Skipping.")

    if callback_query.from_user.id not in admin_ids_int:
        logger.warning(f"User {callback_query.from_user.id} (not an admin) tried to use delete user callback.")
        await callback_query.answer("Permission denied.", show_alert=True) # Notify user
        return

    await callback_query.answer() # Acknowledge the callback

    # Edit the original message (e.g., remove keyboard or show status)
    # For now, let's just edit the text. A more sophisticated approach might remove the keyboard.
    admin_lang = get_admin_lang_code() # For localization
    _ = get_translator(admin_lang)
    processing_text = _(KEY_PROCESSING_DELETE_REQUEST) # Using simple string for now
    try:
        await callback_query.message.edit_text(processing_text)
    except Exception as e:
        logger.debug(f"Could not edit message text on delete_user_start_handler: {e}")


    # Send a new message asking for user identifier
    prompt_text = _(KEY_PROMPT_USER_IDENTIFIER_FOR_DELETION) # Using simple string for now
    await callback_query.message.answer(prompt_text)

    # Set the state
    await state.set_state(AdminActions.awaiting_user_identifier_for_deletion)
    logger.info(f"Admin {callback_query.from_user.id} initiated user deletion process. Awaiting user identifier.")


@router.message(AdminActions.awaiting_user_identifier_for_deletion)
async def receive_user_identifier_for_deletion_handler(message: types.Message, state: FSMContext, db_session: AsyncSession):
    identifier = message.text
    admin_lang = get_admin_lang_code() # For localization
    _ = get_translator(admin_lang)

    if not identifier or len(identifier) == 0:
        reply_text = _(KEY_INVALID_INPUT_FOR_DELETION) # Simple string
        await message.reply(reply_text)
        # We could keep the state or clear it. For now, let's clear, forcing them to restart.
        # Potentially, we could reprompt.
        await state.clear()
        return

    user_to_delete = await get_user_by_identifier(db_session, identifier)

    if user_to_delete:
        deletion_successful = await delete_telegram_registration(db_session, user_to_delete.telegram_id)
        if deletion_successful:
            reply_text = _(KEY_USER_DELETED_SUCCESSFULLY).format(identifier=identifier) # Simple string
            await message.reply(reply_text)
            logger.info(f"Admin {message.from_user.id} successfully deleted user: {identifier} (TG ID: {user_to_delete.telegram_id})")
        else:
            reply_text = _(KEY_FAILED_TO_DELETE_USER).format(identifier=identifier) # Simple string
            await message.reply(reply_text)
            logger.error(f"Admin {message.from_user.id} failed to delete user: {identifier} (TG ID: {user_to_delete.telegram_id}) from database, though user was found.")
    else:
        reply_text = _(KEY_USER_NOT_FOUND).format(identifier=identifier) # Simple string
        await message.reply(reply_text)
        logger.info(f"Admin {message.from_user.id} attempted to delete user: {identifier}, but user was not found.")

    await state.clear()


@router.message(Command("generate"))
async def generate_deeplink_handler(message: types.Message, bot: AiogramBot, db_session: AsyncSession):
    # Check if the user is an admin
    # Ensure ADMIN_IDS in config contains integers or strings that can be cast to int
    # For this comparison, message.from_user.id is an int.
    # config.ADMIN_IDS stores them as strings if loaded from .env, cast them for comparison.
    admin_ids_int = []
    if config.ADMIN_IDS:
        for admin_id_str in config.ADMIN_IDS:
            try:
                admin_ids_int.append(int(admin_id_str))
            except ValueError:
                logger.warning(f"Invalid admin ID in config: {admin_id_str}. Skipping.")

    if message.from_user.id not in admin_ids_int:
        logger.warning(f"User {message.from_user.id} (not an admin) tried to use /generate.")
        # Optionally send a "permission denied" message if desired, or just return.
        # For now, just returning to avoid notifying non-admins about admin commands.
        return

    # Check if deeplink registration is enabled
    if not config.TELEGRAM_DEEPLINK_REGISTRATION_ENABLED:
        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)
        await message.reply(_("Deeplink registration is currently disabled in the configuration."))
        return

    try:
        token = secrets.token_urlsafe(32)
        # For simplicity, let's make token expiry a fixed value, e.g. 5 minutes
        # This could be made configurable via config.py if needed.
        token_expiry_minutes = 5
        expires_at = datetime.utcnow() + timedelta(minutes=token_expiry_minutes)
        acting_admin_id = message.from_user.id

        await create_deeplink_token(
            db_session,
            token_str=token,
            expires_at=expires_at,
            generated_by_admin_id=acting_admin_id
        )

        bot_info = await bot.get_me()
        bot_username = bot_info.username
        deeplink_url = f"https://t.me/{bot_username}?start={token}"

        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)

        # Ensure the deeplink URL itself is not misinterpreted by MarkdownV2
        # by escaping any special Markdown characters within it if necessary,
        # though for a URL, this is usually not an issue with backticks.
        # For simplicity, assuming deeplink_url is safe for direct insertion into MarkdownV2 backticks.
        # Reply with only the deeplink URL formatted as code.
        reply_text = f"`{deeplink_url}`"
        await message.reply(reply_text, parse_mode="MarkdownV2")
        logger.info(f"Admin {acting_admin_id} generated deeplink: {deeplink_url}")

    except Exception as e:
        logger.error(f"Error generating deeplink: {e}", exc_info=True)
        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)
        await message.reply(_("An error occurred while generating the deeplink."))


logger.info("Admin router initialized with /generate command handler.")
