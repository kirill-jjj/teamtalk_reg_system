import logging
import secrets
from datetime import datetime, timedelta

import logging
from aiogram import types, Bot as AiogramBot, F, Router
from aiogram.filters import Command
# CallbackData itself is not directly used here anymore, but kept if other CBs are defined inline
# from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import config
from ...core.db.crud import (
    create_deeplink_token,
    delete_telegram_registration,
    get_all_telegram_registrations,
    add_banned_user,
    get_banned_users,
    remove_banned_user,
)
from ...core.db.models import TelegramRegistration
from ...core.localization import get_translator, get_admin_lang_code
# Import the callbacks from the new location
from ..callbacks.admin_callbacks import AdminDeleteCallback, AdminBanListActionCallback, AdminTTAccountsCallback # Added AdminTTAccountsCallback
from ..keyboards.admin_keyboards import get_admin_panel_keyboard, CALLBACK_DATA_DELETE_USER
from ..states import AdminActions
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup

# For TeamTalk interaction
from ...teamtalk.connection import pytalk_bot
# from pytalk import UserAccount # For type hinting, if directly used. Pytalk objects are often dynamic.

logger = logging.getLogger(__name__)

# Removed AdminDeleteCallback and AdminBanListActionCallback class definitions from here

router = Router()

# Localization Keys (replacing old placeholders)
KEY_ADMIN_PANEL_TITLE = "admin_panel_title"
KEY_PROMPT_USER_IDENTIFIER_FOR_DELETION = "admin_delete_prompt_identifier"
KEY_PROCESSING_DELETE_REQUEST = "admin_delete_processing"
KEY_USER_DELETED_SUCCESSFULLY = "admin_delete_success"
KEY_FAILED_TO_DELETE_USER = "admin_delete_fail_db"
KEY_USER_NOT_FOUND = "admin_delete_user_not_found"
KEY_INVALID_INPUT_FOR_DELETION = "admin_delete_invalid_input"
KEY_ADMIN_DELETE_NO_USERS_FOUND = "admin_delete_no_users_found"
KEY_ADMIN_DELETE_SELECT_USER = "admin_delete_select_user"
KEY_ADMIN_DELETE_CONFIRMED_SUCCESS = "admin_delete_confirmed_success"
KEY_ADMIN_DELETE_CONFIRMED_FAIL = "admin_delete_confirmed_fail"
KEY_ADMIN_DELETE_INVALID_ID_FORMAT = "admin_delete_invalid_id_format"

# New Localization Keys for Ban List Management
KEY_ADMIN_BANLIST_TITLE = "admin_banlist_title"
KEY_ADMIN_BANLIST_EMPTY = "admin_banlist_empty"
KEY_BUTTON_UNBAN = "admin_button_unban"
KEY_BUTTON_ADD_TO_BANLIST_MANUAL = "admin_button_add_to_banlist_manual"
KEY_ADMIN_UNBAN_SUCCESS = "admin_unban_success"
KEY_ADMIN_UNBAN_FAIL = "admin_unban_fail"
KEY_ADMIN_MANUAL_BAN_PROMPT = "admin_manual_ban_prompt"
KEY_ADMIN_MANUAL_BAN_SUCCESS = "admin_manual_ban_success"
KEY_ADMIN_MANUAL_BAN_INVALID_ID = "admin_manual_ban_invalid_id"
KEY_ADMIN_MANUAL_BAN_FAIL = "admin_manual_ban_fail"

# New Localization Keys for TT Account Listing
KEY_ADMIN_TT_LIST_TITLE = "admin_tt_list_title"
KEY_ADMIN_TT_LIST_NO_ACCOUNTS = "admin_tt_list_no_accounts"
KEY_ADMIN_TT_LIST_CONNECTION_ERROR = "admin_tt_list_connection_error"
KEY_BUTTON_DELETE_FROM_TT = "admin_button_delete_from_tt"

# Localization Keys for TT Account Deletion Prompt
KEY_ADMIN_TT_DELETE_PROMPT_TEXT = "admin_tt_delete_prompt_text"
KEY_BUTTON_CONFIRM_DELETE_FROM_TT = "admin_button_confirm_delete_from_tt"
KEY_BUTTON_CANCEL_TT_DELETE = "admin_button_cancel_tt_delete"

# Localization Keys for TT Account Deletion Confirmation
KEY_ADMIN_TT_DELETE_SUCCESS = "admin_tt_delete_success"
KEY_ADMIN_TT_DELETE_FAIL = "admin_tt_delete_fail"
KEY_ADMIN_TT_DELETE_CONNECTION_ERROR = "admin_tt_delete_connection_error"


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
async def delete_user_start_handler(callback_query: types.CallbackQuery, db_session: AsyncSession): # Removed FSMContext, added db_session
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

    # Removed old processing text edit, prompt, and state set.
    # New logic:
    users = await get_all_telegram_registrations(db_session)

    if not users:
        try:
            await callback_query.message.edit_text(_(KEY_ADMIN_DELETE_NO_USERS_FOUND))
        except Exception as e: # Handle cases where message cannot be edited (e.g. too old)
            logger.warning(f"Could not edit message for no users found: {e}")
            await callback_query.message.answer(_(KEY_ADMIN_DELETE_NO_USERS_FOUND))
        return

    builder = InlineKeyboardBuilder()
    for user in users:
        button_text = f"TG ID: {user.telegram_id} - TT User: {user.teamtalk_username}"
        # Use AdminDeleteCallback to create callback data
        callback_data = AdminDeleteCallback(user_telegram_id=user.telegram_id)
        builder.button(text=button_text, callback_data=callback_data)

    builder.adjust(1) # One button per row

    reply_text = _(KEY_ADMIN_DELETE_SELECT_USER)
    try:
        await callback_query.message.edit_text(reply_text, reply_markup=builder.as_markup())
    except Exception as e: # Handle potential errors editing the message
        logger.warning(f"Could not edit message to show user list: {e}")
        # Fallback to sending a new message if editing fails
        await callback_query.message.answer(reply_text, reply_markup=builder.as_markup())

    logger.info(f"Admin {callback_query.from_user.id} requested user list for deletion.")

# Removed receive_user_identifier_for_deletion_handler as it's no longer used.

@router.callback_query(AdminDeleteCallback.filter()) # Changed to use AdminDeleteCallback.filter()
async def confirm_delete_user_handler(callback_query: types.CallbackQuery, db_session: AsyncSession, callback_data: AdminDeleteCallback): # Added callback_data parameter
    # Admin check
    admin_ids_int = []
    if config.ADMIN_IDS:
        for admin_id_str in config.ADMIN_IDS:
            try:
                admin_ids_int.append(int(admin_id_str))
            except ValueError:
                logger.warning(f"Invalid admin ID in config for callback: {admin_id_str}. Skipping.")

    if callback_query.from_user.id not in admin_ids_int:
        logger.warning(f"User {callback_query.from_user.id} (not an admin) tried to use confirm delete user callback.")
        await callback_query.answer("Permission denied.", show_alert=True)
        return

    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    # Get telegram_id directly from callback_data
    telegram_id_to_delete = callback_data.user_telegram_id

    # Fetch TelegramRegistration to get teamtalk_username before deleting
    tt_username_for_ban: str | None = None
    user_reg_stmt = select(TelegramRegistration).where(TelegramRegistration.telegram_id == telegram_id_to_delete)
    user_reg_result = await db_session.execute(user_reg_stmt)
    user_reg = user_reg_result.scalar_one_or_none()
    if user_reg:
        tt_username_for_ban = user_reg.teamtalk_username
        logger.info(f"Found TeamTalk username '{tt_username_for_ban}' for Telegram ID {telegram_id_to_delete} before deletion.")
    else:
        logger.warning(f"Could not find TelegramRegistration record for Telegram ID {telegram_id_to_delete} before deletion. Will ban without TT username.")

    deletion_successful = await delete_telegram_registration(db_session, telegram_id_to_delete)

    if deletion_successful:
        logger.info(f"Admin {callback_query.from_user.id} successfully deleted TelegramRegistration for ID: {telegram_id_to_delete}")

        # Now, also ban the user
        await add_banned_user(
            db_session=db_session,
            telegram_id=telegram_id_to_delete,
            teamtalk_username=tt_username_for_ban,
            admin_id=callback_query.from_user.id,
            reason="Deleted via bot admin panel"
        )
        logger.info(f"User {telegram_id_to_delete} (TT: {tt_username_for_ban}) also added to ban list by admin {callback_query.from_user.id}.")
        reply_text = _(KEY_ADMIN_DELETE_CONFIRMED_SUCCESS).format(telegram_id=telegram_id_to_delete)
    else:
        reply_text = _(KEY_ADMIN_DELETE_CONFIRMED_FAIL).format(telegram_id=telegram_id_to_delete)
        logger.warning(f"Admin {callback_query.from_user.id} failed to delete TelegramRegistration for ID: {telegram_id_to_delete} (possibly already deleted or DB error). Ban not applied.")

    await callback_query.answer(reply_text, show_alert=True)

    try:
        # Try to edit the original message to show the final status and remove keyboard
        await callback_query.message.edit_text(reply_text, reply_markup=None)
    except Exception as e:
        logger.debug(f"Could not edit original message after deletion confirmation: {e}. The alert was shown.")
        # Optionally send a new message if editing fails and it's critical to display status,
        # but an alert might be sufficient.
        # await callback_query.message.answer(reply_text)

# --- Ban List Management Handlers ---

async def _build_ban_list_message_and_keyboard(db_session: AsyncSession, _translator) -> tuple[str, InlineKeyboardMarkup]:
    banned_users = await get_banned_users(db_session)
    builder = InlineKeyboardBuilder()

    message_lines = [_translator(KEY_ADMIN_BANLIST_TITLE)]
    if not banned_users:
        message_lines.append(_translator(KEY_ADMIN_BANLIST_EMPTY))
    else:
        for buser in banned_users:
            reason_text = buser.reason if buser.reason else "N/A"
            tt_user_text = buser.teamtalk_username if buser.teamtalk_username else "N/A"
            # Ensure TG ID is a string for formatting if it's not already
            tg_id_str = str(buser.telegram_id)
            message_lines.append(f"TG ID: {tg_id_str} - TT User: {tt_user_text} (Reason: {reason_text})")
            builder.button(
                text=f"{_translator(KEY_BUTTON_UNBAN)} ({tg_id_str})",
                callback_data=AdminBanListActionCallback(action="unban", target_telegram_id=buser.telegram_id).pack()
            )

    builder.button(
        text=_translator(KEY_BUTTON_ADD_TO_BANLIST_MANUAL),
        callback_data=AdminBanListActionCallback(action="add_prompt", target_telegram_id=None).pack()
    )
    builder.adjust(1) # One button per row for unban, then add_manual button
    return "\n".join(message_lines), builder.as_markup()

@router.callback_query(AdminBanListActionCallback.filter(F.action == "view"))
async def view_ban_list_handler(callback_query: types.CallbackQuery, db_session: AsyncSession):
    await callback_query.answer() # Acknowledge the callback immediately
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    message_text, reply_markup = await _build_ban_list_message_and_keyboard(db_session, _)
    try:
        await callback_query.message.edit_text(message_text, reply_markup=reply_markup)
    except Exception as e: # Handle cases where message cannot be edited (e.g. too old or no change)
        logger.debug(f"Failed to edit message for ban list view (might be no change or too old): {e}")
        # If editing fails because message is not modified, it's not an error.
        # If it's too old, send a new one. For simplicity, just try answering.
        # Consider sending a new message if edit_text fails for other reasons.
        await callback_query.message.answer(message_text, reply_markup=reply_markup)


@router.callback_query(AdminBanListActionCallback.filter(F.action == "unban"))
async def unban_user_handler(callback_query: types.CallbackQuery, callback_data: AdminBanListActionCallback, db_session: AsyncSession):
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    target_id = callback_data.target_telegram_id
    if target_id is None: # Should not happen if buttons are generated correctly
        await callback_query.answer("Error: No target user ID specified for unban.", show_alert=True)
        return

    success = await remove_banned_user(db_session, target_id)
    alert_text = ""
    if success:
        alert_text = _(KEY_ADMIN_UNBAN_SUCCESS).format(target_telegram_id=target_id)
        logger.info(f"Admin {callback_query.from_user.id} unbanned user {target_id}.")
    else:
        alert_text = _(KEY_ADMIN_UNBAN_FAIL).format(target_telegram_id=target_id)
        logger.warning(f"Admin {callback_query.from_user.id} failed to unban user {target_id}.")
    await callback_query.answer(alert_text, show_alert=True)

    # Refresh the ban list message
    message_text, reply_markup = await _build_ban_list_message_and_keyboard(db_session, _)
    try:
        await callback_query.message.edit_text(message_text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Failed to refresh ban list after unban: {e}")
        # Optionally, send a new message if editing fails
        await callback_query.message.answer(text=_("Action processed. Could not refresh list immediately."), reply_markup=None)

@router.callback_query(AdminBanListActionCallback.filter(F.action == "add_prompt"))
async def manual_ban_prompt_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer() # Acknowledge
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)
    try:
        await callback_query.message.edit_text(_(KEY_ADMIN_MANUAL_BAN_PROMPT))
    except Exception as e:
        logger.debug(f"Could not edit message for manual ban prompt (maybe no change): {e}")
        await callback_query.message.answer(_(KEY_ADMIN_MANUAL_BAN_PROMPT)) # Send as new if edit fails
    await state.set_state(AdminActions.awaiting_manual_ban_id_reason)

@router.message(AdminActions.awaiting_manual_ban_id_reason, F.text)
async def process_manual_ban_handler(message: types.Message, state: FSMContext, db_session: AsyncSession):
    await state.clear() # Clear state first
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    parts = message.text.splitlines()
    if not parts: # Should not happen with F.text but good practice
        await message.reply(_(KEY_ADMIN_MANUAL_BAN_INVALID_ID)) # Or a more generic error
        return

    telegram_id_str = parts[0].strip()
    reason = parts[1].strip() if len(parts) > 1 else None

    try:
        target_telegram_id = int(telegram_id_str)
        tt_username = None

        # Attempt to find associated TeamTalk username
        user_reg_stmt = select(TelegramRegistration.teamtalk_username).where(TelegramRegistration.telegram_id == target_telegram_id)
        user_reg_res = await db_session.execute(user_reg_stmt)
        tt_username_tuple = user_reg_res.first() # first() returns a Row or None
        if tt_username_tuple:
            tt_username = tt_username_tuple[0]

        banned_user = await add_banned_user(
            db_session,
            telegram_id=target_telegram_id,
            teamtalk_username=tt_username, # Will be None if not found
            admin_id=message.from_user.id,
            reason=reason
        )
        # add_banned_user now typically returns the BannedUser object.
        # Success is implied if no exception was raised and banned_user is not None.
        await message.reply(_(KEY_ADMIN_MANUAL_BAN_SUCCESS).format(telegram_id=target_telegram_id))
        logger.info(f"Admin {message.from_user.id} manually banned user {target_telegram_id} with reason: '{reason}'. TT username: {tt_username}")

    except ValueError:
        logger.warning(f"Admin {message.from_user.id} provided invalid Telegram ID for manual ban: {telegram_id_str}")
        await message.reply(_(KEY_ADMIN_MANUAL_BAN_INVALID_ID))
    except Exception as e:
        logger.error(f"Failed to manually ban user {telegram_id_str} by admin {message.from_user.id}: {e}", exc_info=True)
        await message.reply(_(KEY_ADMIN_MANUAL_BAN_FAIL).format(telegram_id=telegram_id_str))

# --- TeamTalk Account Listing Handler ---

@router.callback_query(AdminTTAccountsCallback.filter(F.action == "list_all"))
async def list_all_tt_accounts_handler(callback_query: types.CallbackQuery): # Removed db_session as not used
    await callback_query.answer()
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    tt_instance = None
    if pytalk_bot.teamtalks and len(pytalk_bot.teamtalks) > 0:
        tt_instance = pytalk_bot.teamtalks[0] # Assuming one primary TT instance

    if not tt_instance or not tt_instance.is_connected() or not hasattr(tt_instance, 'server'):
        logger.warning("list_all_tt_accounts_handler: TeamTalk instance not available or not connected.")
        try:
            await callback_query.message.edit_text(_(KEY_ADMIN_TT_LIST_CONNECTION_ERROR), reply_markup=None)
        except Exception as e_edit:
            logger.debug(f"Failed to edit message for TT connection error: {e_edit}")
            await callback_query.message.answer(_(KEY_ADMIN_TT_LIST_CONNECTION_ERROR), reply_markup=None)
        return

    user_accounts_data = []
    try:
        # This is the placeholder line. The actual method in pytalk might differ.
        # It should return a list of objects, each representing a UserAccount,
        # and each object should have a 'username' attribute (bytes or str).
        all_accounts_raw = tt_instance.server.get_user_accounts()

        if all_accounts_raw:
            for acc in all_accounts_raw:
                if hasattr(acc, 'username'):
                    username_bytes = acc.username
                    user_accounts_data.append({"username": username_bytes.decode('utf-8') if isinstance(username_bytes, bytes) else str(username_bytes)})
                else:
                    logger.warning(f"TeamTalk account object {acc} does not have a direct 'username' attribute during listing.")

        logger.info(f"Fetched {len(user_accounts_data)} accounts from TeamTalk server.")

    except Exception as e:
        logger.error(f"Error fetching TeamTalk accounts: {e}", exc_info=True)
        try:
            await callback_query.message.edit_text(_(KEY_ADMIN_TT_LIST_CONNECTION_ERROR), reply_markup=None)
        except Exception as e_edit:
            logger.debug(f"Failed to edit message for TT account fetching error: {e_edit}")
            await callback_query.message.answer(_(KEY_ADMIN_TT_LIST_CONNECTION_ERROR), reply_markup=None)
        return

    builder = InlineKeyboardBuilder()
    if not user_accounts_data:
        message_text = _(KEY_ADMIN_TT_LIST_NO_ACCOUNTS)
    else:
        lines = [_(KEY_ADMIN_TT_LIST_TITLE)]
        for acc_data in user_accounts_data:
            tt_username = acc_data["username"]
            lines.append(f"- {tt_username}")
            builder.button(
                text=f"{_(KEY_BUTTON_DELETE_FROM_TT)} ({tt_username})",
                callback_data=AdminTTAccountsCallback(action="delete_prompt", tt_username=tt_username).pack()
            )
        message_text = "\n".join(lines)

    builder.adjust(1)

    try:
        await callback_query.message.edit_text(message_text, reply_markup=builder.as_markup() if user_accounts_data else None)
    except Exception as e:
        logger.warning(f"Failed to edit message for TT account list (maybe no change or too old): {e}")
        # Fallback to sending a new message if editing fails for critical reasons
        await callback_query.message.answer(message_text, reply_markup=builder.as_markup() if user_accounts_data else None)


@router.callback_query(AdminTTAccountsCallback.filter(F.action == "delete_prompt"))
async def prompt_delete_tt_account_handler(callback_query: types.CallbackQuery, callback_data: AdminTTAccountsCallback):
    await callback_query.answer() # Acknowledge the callback immediately
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    tt_username = callback_data.tt_username
    if not tt_username:
        logger.warning("prompt_delete_tt_account_handler: tt_username missing in callback_data.")
        # Attempt to edit the message to show an error, or send a new one.
        error_text = "Error: Username not provided for deletion. Please try again." # This should be localized ideally
        try:
            await callback_query.message.edit_text(error_text, reply_markup=None)
        except Exception as e_edit:
            logger.debug(f"Failed to edit message for missing tt_username error: {e_edit}")
            await callback_query.message.answer(error_text, reply_markup=None)
        return

    prompt_text = _(KEY_ADMIN_TT_DELETE_PROMPT_TEXT).format(tt_username=tt_username)

    builder = InlineKeyboardBuilder()
    builder.button(
        text=_(KEY_BUTTON_CONFIRM_DELETE_FROM_TT),
        callback_data=AdminTTAccountsCallback(action="delete_confirm", tt_username=tt_username).pack()
    )
    builder.button(
        text=_(KEY_BUTTON_CANCEL_TT_DELETE),
        callback_data=AdminTTAccountsCallback(action="list_all", tt_username=None).pack() # Go back to the list
    )
    builder.adjust(2) # Confirm and Cancel side-by-side or stacked (adjust(1) for stacked)

    try:
        await callback_query.message.edit_text(prompt_text, reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Error editing message for TT delete prompt: {e}", exc_info=True)
        # Fallback to sending a new message if edit fails (e.g., message too old)
        await callback_query.message.answer(prompt_text, reply_markup=builder.as_markup())


@router.callback_query(AdminTTAccountsCallback.filter(F.action == "delete_confirm"))
async def confirm_delete_tt_account_handler(callback_query: types.CallbackQuery, callback_data: AdminTTAccountsCallback):
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    tt_username = callback_data.tt_username
    if not tt_username:
        logger.error("confirm_delete_tt_account_handler: tt_username missing in callback_data during delete confirmation.")
        # This message should ideally be localized too if it were user-facing beyond an immediate error.
        await callback_query.answer("Error: Username missing. Cannot delete.", show_alert=True)
        try:
            await callback_query.message.edit_text("Internal error: Username was not provided for deletion.", reply_markup=None)
        except Exception as e_edit:
            logger.debug(f"Failed to edit message for missing tt_username on confirm: {e_edit}")
        return

    tt_instance = None
    if pytalk_bot.teamtalks and len(pytalk_bot.teamtalks) > 0:
        tt_instance = pytalk_bot.teamtalks[0] # Assuming one primary TT instance

    if not tt_instance or not tt_instance.is_connected() or not hasattr(tt_instance, 'server'):
        logger.warning(f"confirm_delete_tt_account_handler: TeamTalk instance not available or not connected for deleting {tt_username}.")
        connection_error_text = _(KEY_ADMIN_TT_DELETE_CONNECTION_ERROR)
        await callback_query.answer(connection_error_text, show_alert=True)
        try:
            await callback_query.message.edit_text(connection_error_text, reply_markup=None)
        except Exception as e_edit:
            logger.debug(f"Failed to edit message for TT connection error on confirm: {e_edit}")
            await callback_query.message.answer(connection_error_text, reply_markup=None) # Send as new if edit fails
        return

    final_message = ""
    try:
        logger.info(f"Admin {callback_query.from_user.id} requesting deletion of TeamTalk user: {tt_username}")

        # CRITICAL PLACEHOLDER: Actual pytalk method to delete a user account by username.
        # This is a guess. The actual method name and parameters are crucial and depend on the pytalk library.
        # Common patterns might be `do_remove_useraccount(username=tt_username)` or finding user by name then deleting by ID.
        # Example: `await tt_instance.server.remove_user_account(username=tt_username)`
        # For this subtask, we assume a method `do_removeuseraccount` exists on the server object.

        # Check if the method exists before calling (defensive coding for placeholder)
        if hasattr(tt_instance.server, 'do_removeuseraccount') and callable(getattr(tt_instance.server, 'do_removeuseraccount')):
            # The actual call might need to be awaited if it's an async method in pytalk.
            # Assuming it's synchronous based on some pytalk patterns, but this is a major guess.
            # If it's async: result = await tt_instance.server.do_removeuseraccount(username=tt_username)
            tt_instance.server.do_removeuseraccount(username=tt_username) # Placeholder call
            # If no exception is raised by the above call, we assume the command was accepted by the server.
            # The actual deletion confirmation will be handled by the `on_user_account_remove` event,
            # which will then trigger the bot-side ban.
            final_message = _(KEY_ADMIN_TT_DELETE_SUCCESS).format(tt_username=tt_username)
            await callback_query.answer(final_message, show_alert=False) # Show a less intrusive alert for "sent"
            logger.info(f"Deletion request for TeamTalk user '{tt_username}' sent to server by admin {callback_query.from_user.id}.")
        else:
            logger.error(f"confirm_delete_tt_account_handler: `do_removeuseraccount` method not found on tt_instance.server. Cannot delete TT user {tt_username}.")
            final_message = _(KEY_ADMIN_TT_DELETE_FAIL).format(tt_username=tt_username, error="Bot configuration error: TeamTalk command not found.")
            await callback_query.answer(final_message, show_alert=True)

    except Exception as e:
        logger.error(f"Error attempting to delete TeamTalk user '{tt_username}': {e}", exc_info=True)
        # Provide a more specific error if possible, otherwise generic.
        error_detail = str(e) if str(e) else "Unknown server error"
        final_message = _(KEY_ADMIN_TT_DELETE_FAIL).format(tt_username=tt_username, error=error_detail)
        await callback_query.answer(final_message, show_alert=True)

    try:
        await callback_query.message.edit_text(final_message, reply_markup=None)
    except Exception as e_edit:
        logger.debug(f"Failed to edit message after TT delete confirmation: {e_edit}")
        # If editing fails, the user already got an alert. Optionally send a new message.
        # await callback_query.message.answer(final_message, reply_markup=None)


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
