from datetime import datetime, timedelta
import logging
import secrets

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup

# CallbackData itself is not directly used here anymore, but kept if other CBs are defined inline
# from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
import pytalk  # New import
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db.crud import (
    add_banned_user,
    create_deeplink_token,
    delete_telegram_registration,
    get_all_telegram_registrations,
    get_banned_users,
    remove_banned_user,
)
from ...core.db.models import TelegramRegistration
from ...core.localization import get_admin_lang_code, get_translator

# For TeamTalk interaction
# Import the callbacks from the new location
from ..callbacks.admin_callbacks import (  # Added AdminTTAccountsCallback
    AdminBanListActionCallback,
    AdminDeleteCallback,
    AdminTTAccountsCallback,
)
from ..keyboards.admin_keyboards import (
    CALLBACK_DATA_DELETE_USER,
    get_admin_panel_keyboard,
)
from ..states import AdminActions

# from pytalk import UserAccount # For type hinting, if directly used. Pytalk objects are often dynamic.

logger = logging.getLogger(__name__)

router = Router()

@router.message(Command("adminpanel"))
async def admin_panel_handler(message: types.Message):
    # Admin check
    if message.from_user.id not in settings.admin_ids:
        logger.warning("User %s (not an admin) tried to use /adminpanel.", message.from_user.id)
        return

    # For now, using a simple string. Localization can be added later.
    admin_lang = get_admin_lang_code() # This would be needed for localization
    _ = get_translator(admin_lang)
    reply_text = _("Admin Panel") # Using simple string for now

    keyboard = get_admin_panel_keyboard()
    await message.reply(reply_text, reply_markup=keyboard)


@router.message(Command("exit"))
async def exit_command_handler(message: types.Message, dispatcher: "Dispatcher"):
    """Handles the /exit command to gracefully shut down the bot."""
    if message.from_user.id not in settings.admin_ids:
        logger.warning("User %s (not an admin) tried to use /exit.", message.from_user.id)
        return

    logger.info("Admin %s initiated bot shutdown.", message.from_user.id)
    await message.reply("Shutting down...")
    await dispatcher.shutdown()


@router.callback_query(F.data == CALLBACK_DATA_DELETE_USER)
async def delete_user_start_handler(callback_query: types.CallbackQuery, db_session: AsyncSession): # Removed FSMContext, added db_session
    admin_lang = get_admin_lang_code() # For localization
    _ = get_translator(admin_lang)
    # Admin check (important for callback queries too)
    if callback_query.from_user.id not in settings.admin_ids:
        logger.warning("User %s (not an admin) tried to use delete user callback.", callback_query.from_user.id)
        await callback_query.answer(_("Permission denied."), show_alert=True) # Notify user
        return

    await callback_query.answer() # Acknowledge the callback

    # Edit the original message (e.g., remove keyboard or show status)
    # For now, let's just edit the text. A more sophisticated approach might remove the keyboard.
    # Removed old processing text edit, prompt, and state set.
    # New logic:

    # Removed old processing text edit, prompt, and state set.
    # New logic:
    users = await get_all_telegram_registrations(db_session)

    if not users:
        try:
            await callback_query.message.edit_text(_("No registered users found to delete."))
        except Exception as e: # Handle cases where message cannot be edited (e.g. too old)
            logger.warning("Could not edit message for no users found: %s", e)
            await callback_query.message.answer(_("No registered users found to delete."))
        return

    builder = InlineKeyboardBuilder()
    for user in users:
        button_text = f"TG ID: {user.telegram_id} - TT User: {user.teamtalk_username}"
        # Use AdminDeleteCallback to create callback data
        callback_data = AdminDeleteCallback(user_telegram_id=user.telegram_id)
        builder.button(text=button_text, callback_data=callback_data)

    builder.adjust(1) # One button per row

    reply_text = _("Select a user to delete:")
    try:
        await callback_query.message.edit_text(reply_text, reply_markup=builder.as_markup())
    except Exception as e: # Handle potential errors editing the message
        logger.warning("Could not edit message to show user list: %s", e)
        # Fallback to sending a new message if editing fails
        await callback_query.message.answer(reply_text, reply_markup=builder.as_markup())

    logger.info("Admin %s requested user list for deletion.", callback_query.from_user.id)


@router.callback_query(AdminDeleteCallback.filter()) # Changed to use AdminDeleteCallback.filter()
async def confirm_delete_user_handler(callback_query: types.CallbackQuery, db_session: AsyncSession, callback_data: AdminDeleteCallback): # Added callback_data parameter
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)
    # Admin check
    if callback_query.from_user.id not in settings.admin_ids:
        logger.warning(f"User {callback_query.from_user.id} (not an admin) tried to use confirm delete user callback.")
        await callback_query.answer(_("Permission denied."), show_alert=True)
        return

    # Get telegram_id directly from callback_data
    telegram_id_to_delete = callback_data.user_telegram_id

    # Fetch TelegramRegistration to get teamtalk_username before deleting
    tt_username_for_ban: str | None = None
    user_reg_stmt = select(TelegramRegistration).where(TelegramRegistration.telegram_id == telegram_id_to_delete)
    user_reg_result = await db_session.execute(user_reg_stmt)
    user_reg = user_reg_result.scalar_one_or_none()
    if user_reg:
        tt_username_for_ban = user_reg.teamtalk_username
        logger.info("Found TeamTalk username '%s' for Telegram ID %s before deletion.", tt_username_for_ban, telegram_id_to_delete)
    else:
        logger.warning("Could not find TelegramRegistration record for Telegram ID %s before deletion. Will ban without TT username.", telegram_id_to_delete)

    deletion_successful = await delete_telegram_registration(db_session, telegram_id_to_delete)

    if deletion_successful:
        logger.info("Admin %s successfully deleted TelegramRegistration for ID: %s", callback_query.from_user.id, telegram_id_to_delete)

        # Now, also ban the user
        await add_banned_user(
            db_session=db_session,
            telegram_id=telegram_id_to_delete,
            teamtalk_username=tt_username_for_ban,
            admin_id=callback_query.from_user.id,
            reason="Deleted via bot admin panel"
        )
        logger.info("User %s (TT: %s) also added to ban list by admin %s.", telegram_id_to_delete, tt_username_for_ban, callback_query.from_user.id)
        reply_text = _("User with Telegram ID {telegram_id} has been deleted and banned.").format(telegram_id=telegram_id_to_delete)
    else:
        reply_text = _("Failed to delete user with Telegram ID {telegram_id}.").format(telegram_id=telegram_id_to_delete)
        logger.warning("Admin %s failed to delete TelegramRegistration for ID: %s (possibly already deleted or DB error). Ban not applied.", callback_query.from_user.id, telegram_id_to_delete)

    await callback_query.answer(reply_text, show_alert=True)

    try:
        # Try to edit the original message to show the final status and remove keyboard
        await callback_query.message.edit_text(reply_text, reply_markup=None)
    except Exception as e:
        logger.debug("Could not edit original message after deletion confirmation: %s. The alert was shown.", e)
        # Optionally send a new message if editing fails and it's critical to display status,
        # but an alert might be sufficient.
        # await callback_query.message.answer(reply_text)

# --- Ban List Management Handlers ---

async def _build_ban_list_message_and_keyboard(db_session: AsyncSession, _translator) -> tuple[str, InlineKeyboardMarkup]:
    banned_users = await get_banned_users(db_session)
    builder = InlineKeyboardBuilder()

    message_lines = [_translator("Banned Users:")]
    if not banned_users:
        message_lines.append(_translator("The ban list is empty."))
    else:
        for buser in banned_users:
            reason_text = buser.reason if buser.reason else "N/A"
            tt_user_text = buser.teamtalk_username if buser.teamtalk_username else "N/A"
            # Ensure TG ID is a string for formatting if it's not already
            tg_id_str = str(buser.telegram_id)
            message_lines.append(f"TG ID: {tg_id_str} - TT User: {tt_user_text} (Reason: {reason_text})")
            builder.button(
                text=f"{_translator('Unban')} ({tg_id_str})",
                callback_data=AdminBanListActionCallback(action="unban", target_telegram_id=buser.telegram_id).pack()
            )

    builder.button(
        text=_translator("Add to Ban List Manually"),
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
        logger.debug("Failed to edit message for ban list view (might be no change or too old): %s", e)
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
        await callback_query.answer(_("Error: No target user ID specified for unban."), show_alert=True)
        return

    success = await remove_banned_user(db_session, target_id)
    alert_text = ""
    if success:
        alert_text = _("User {target_telegram_id} has been unbanned.").format(target_telegram_id=target_id)
        logger.info("Admin %s unbanned user %s.", callback_query.from_user.id, target_id)
    else:
        alert_text = _("Failed to unban user {target_telegram_id}.").format(target_telegram_id=target_id)
        logger.warning("Admin %s failed to unban user %s.", callback_query.from_user.id, target_id)
    await callback_query.answer(alert_text, show_alert=True)

    # Refresh the ban list message
    message_text, reply_markup = await _build_ban_list_message_and_keyboard(db_session, _)
    try:
        await callback_query.message.edit_text(message_text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning("Failed to refresh ban list after unban: %s", e)
        # Optionally, send a new message if editing fails
        await callback_query.message.answer(text=_("Action processed. Could not refresh list immediately."), reply_markup=None)

@router.callback_query(AdminBanListActionCallback.filter(F.action == "add_prompt"))
async def manual_ban_prompt_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer() # Acknowledge
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)
    try:
        await callback_query.message.edit_text(_("Please enter the Telegram ID and reason for the ban on separate lines."))
    except Exception as e:
        logger.debug("Could not edit message for manual ban prompt (maybe no change): %s", e)
        await callback_query.message.answer(_("Please enter the Telegram ID and reason for the ban on separate lines.")) # Send as new if edit fails
    await state.set_state(AdminActions.awaiting_manual_ban_id_reason)

@router.message(AdminActions.awaiting_manual_ban_id_reason, F.text)
async def process_manual_ban_handler(message: types.Message, state: FSMContext, db_session: AsyncSession):
    await state.clear() # Clear state first
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    parts = message.text.splitlines()
    if not parts: # Should not happen with F.text but good practice
        await message.reply(_("Invalid Telegram ID provided.")) # Or a more generic error
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
        await message.reply(_("User {telegram_id} has been manually banned.").format(telegram_id=target_telegram_id))
        logger.info("Admin %s manually banned user %s with reason: '%s'. TT username: %s", message.from_user.id, target_telegram_id, reason, tt_username)

    except ValueError:
        logger.warning("Admin %s provided invalid Telegram ID for manual ban: %s", message.from_user.id, telegram_id_str)
        await message.reply(_("Invalid Telegram ID provided."))
    except Exception as e:
        logger.error("Failed to manually ban user %s by admin %s: %s", telegram_id_str, message.from_user.id, e, exc_info=True)
        await message.reply(_("Failed to manually ban user {telegram_id}.").format(telegram_id=telegram_id_str))

# --- TeamTalk Account Listing Handler ---

@router.callback_query(AdminTTAccountsCallback.filter(F.action == "list_all"))
async def list_all_tt_accounts_handler(pytalk_bot_instance: pytalk.TeamTalkBot, callback_query: types.CallbackQuery):
    await callback_query.answer()
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    tt_instance = None
    if pytalk_bot_instance.teamtalks and len(pytalk_bot_instance.teamtalks) > 0:
        tt_instance = pytalk_bot_instance.teamtalks[0] # Assuming one primary TT instance

    if not tt_instance or not tt_instance.connected or not hasattr(tt_instance, 'server'): # Changed is_connected() to connected
        logger.warning("list_all_tt_accounts_handler: TeamTalk instance not available or not connected.")
        try:
            await callback_query.message.edit_text(_("Could not connect to the TeamTalk server to get the list of accounts."), reply_markup=None)
        except Exception as e_edit:
            logger.debug("Failed to edit message for TT connection error: %s", e_edit)
            await callback_query.message.answer(_("Could not connect to the TeamTalk server to get the list of accounts."), reply_markup=None)
        return

    user_accounts_display = []
    try:
        # Use the correct async method: list_user_accounts()
        # This method is expected to return a List[TeamTalkUserAccount]
        user_accounts_sdk = await tt_instance.list_user_accounts()

        if user_accounts_sdk:
            for acc_sdk in user_accounts_sdk: # acc_sdk is a TeamTalkUserAccount object
                # The TeamTalkUserAccount object should have a 'username' attribute.
                # It might also have other attributes like user_id, user_type, etc.
                if hasattr(acc_sdk, 'username'):
                    raw_username = acc_sdk.username
                    username_str = raw_username.decode('utf-8') if isinstance(raw_username, bytes) else str(raw_username)
                    user_accounts_display.append({"username": username_str})
                else:
                    # This case should ideally not happen if list_user_accounts() returns standardized objects.
                    logger.warning("TeamTalk UserAccount object %s (type: %s) does not have 'username' attribute.", acc_sdk, type(acc_sdk))

        logger.info("Fetched %s accounts from TeamTalk server using list_user_accounts.", len(user_accounts_display))

    except Exception as e:
        logger.error("Error fetching TeamTalk accounts using list_user_accounts: %s", e, exc_info=True)
        try:
            await callback_query.message.edit_text(_("Could not connect to the TeamTalk server to get the list of accounts."), reply_markup=None)
        except Exception as e_edit:
            logger.debug("Failed to edit message for TT account fetching error: %s", e_edit)
            await callback_query.message.answer(_("Could not connect to the TeamTalk server to get the list of accounts."), reply_markup=None)
        return

    builder = InlineKeyboardBuilder()
    if not user_accounts_display: # Check the processed list
        message_text = _("No TeamTalk accounts found on the server.")
    else:
        lines = [_("TeamTalk Accounts:")]
        for acc_data in user_accounts_display: # Iterate over the processed list
            tt_username = acc_data["username"]
            lines.append(f"- {tt_username}")
            builder.button(
                text=f"{_('Delete from TeamTalk')} ({tt_username})",
                callback_data=AdminTTAccountsCallback(action="delete_prompt", tt_username=tt_username).pack()
            )
        message_text = "\n".join(lines)

    builder.adjust(1)

    try:
        await callback_query.message.edit_text(message_text, reply_markup=builder.as_markup() if user_accounts_display else None)
    except Exception as e:
        logger.warning("Failed to edit message for TT account list (maybe no change or too old): %s", e)
        # Fallback to sending a new message if editing fails for critical reasons
        await callback_query.message.answer(message_text, reply_markup=builder.as_markup() if user_accounts_display else None)


@router.callback_query(AdminTTAccountsCallback.filter(F.action == "delete_prompt"))
async def prompt_delete_tt_account_handler(callback_query: types.CallbackQuery, callback_data: AdminTTAccountsCallback):
    await callback_query.answer() # Acknowledge the callback immediately
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    tt_username = callback_data.tt_username
    if not tt_username:
        logger.warning("prompt_delete_tt_account_handler: tt_username missing in callback_data.")
        # Attempt to edit the message to show an error, or send a new one.
        error_text = _("Error: Username not provided for deletion. Please try again.") # This should be localized ideally
        try:
            await callback_query.message.edit_text(error_text, reply_markup=None)
        except Exception as e_edit:
            logger.debug("Failed to edit message for missing tt_username error: %s", e_edit)
            await callback_query.message.answer(error_text, reply_markup=None)
        return

    prompt_text = _("Are you sure you want to delete the TeamTalk user '{tt_username}'?").format(tt_username=tt_username)

    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("Confirm Delete"),
        callback_data=AdminTTAccountsCallback(action="delete_confirm", tt_username=tt_username).pack()
    )
    builder.button(
        text=_("Cancel"),
        callback_data=AdminTTAccountsCallback(action="list_all", tt_username=None).pack() # Go back to the list
    )
    builder.adjust(2) # Confirm and Cancel side-by-side or stacked (adjust(1) for stacked)

    try:
        await callback_query.message.edit_text(prompt_text, reply_markup=builder.as_markup())
    except Exception as e:
        logger.error("Error editing message for TT delete prompt: %s", e, exc_info=True)
        # Fallback to sending a new message if edit fails (e.g., message too old)
        await callback_query.message.answer(prompt_text, reply_markup=builder.as_markup())


@router.callback_query(AdminTTAccountsCallback.filter(F.action == "delete_confirm"))
async def confirm_delete_tt_account_handler(pytalk_bot_instance: pytalk.TeamTalkBot, callback_query: types.CallbackQuery, callback_data: AdminTTAccountsCallback):
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    tt_username = callback_data.tt_username
    if not tt_username:
        logger.error("confirm_delete_tt_account_handler: tt_username missing in callback_data during delete confirmation.")
        # This message should ideally be localized too if it were user-facing beyond an immediate error.
        await callback_query.answer(_("Error: Username missing. Cannot delete."), show_alert=True)
        try:
            await callback_query.message.edit_text(_("Internal error: Username was not provided for deletion."), reply_markup=None)
        except Exception as e_edit:
            logger.debug("Failed to edit message for missing tt_username on confirm: %s", e_edit)
        return

    tt_instance = None
    if pytalk_bot_instance.teamtalks and len(pytalk_bot_instance.teamtalks) > 0:
        tt_instance = pytalk_bot_instance.teamtalks[0] # Assuming one primary TT instance

    if not tt_instance or not tt_instance.connected or not hasattr(tt_instance, 'server'): # Changed is_connected() to connected
        logger.warning("confirm_delete_tt_account_handler: TeamTalk instance not available or not connected for deleting %s.", tt_username)
        connection_error_text = _("Could not connect to the TeamTalk server to delete the account.")
        await callback_query.answer(connection_error_text, show_alert=True)
        try:
            await callback_query.message.edit_text(connection_error_text, reply_markup=None)
        except Exception as e_edit:
            logger.debug("Failed to edit message for TT connection error on confirm: %s", e_edit)
            await callback_query.message.answer(connection_error_text, reply_markup=None) # Send as new if edit fails
        return

    final_message = ""
    try:
        logger.info("Admin %s requesting deletion of TeamTalk user: %s", callback_query.from_user.id, tt_username)

        # Call the correct pytalk method.
        # Assumed to be synchronous based on documentation (def delete_user_account(...)).
        deletion_command_sent = tt_instance.delete_user_account(username=tt_username)

        if deletion_command_sent: # Returns True on success as per pytalk docs
            final_message = _("TeamTalk user '{tt_username}' was successfully deleted.").format(tt_username=tt_username)
            # Changed show_alert to True as this is the final user feedback on this action.
            await callback_query.answer(final_message, show_alert=True)
            logger.info("TeamTalk user '%s' deletion command successfully processed by bot for admin %s. Waiting for server event for actual ban.", tt_username, callback_query.from_user.id)
        else:
            # This case implies the method returned False without raising an exception,
            # which might be unexpected if the library usually raises for errors.
            logger.warning("TeamTalk user '%s' deletion command returned False for admin %s without raising an exception.", tt_username, callback_query.from_user.id)
            final_message = _("Failed to delete TeamTalk user '{tt_username}'. Reason: {error}").format(tt_username=tt_username, error="TeamTalk command indicated failure but no specific error.")
            await callback_query.answer(final_message, show_alert=True)

    except PermissionError as e: # Specific exception from pytalk for permission issues
        logger.error("Permission error deleting TeamTalk user '%s' by admin %s: %s", tt_username, callback_query.from_user.id, e, exc_info=True)
        final_message = _("Failed to delete TeamTalk user '{tt_username}'. Reason: {error}").format(tt_username=tt_username, error=f"Permission denied: {e}")
        await callback_query.answer(final_message, show_alert=True)
    except ValueError as e: # Specific exception from pytalk (e.g., user not found, invalid username)
        logger.error("Value error (e.g., user not found) deleting TeamTalk user '%s' by admin %s: %s", tt_username, callback_query.from_user.id, e, exc_info=True)
        final_message = _("Failed to delete TeamTalk user '{tt_username}'. Reason: {error}").format(tt_username=tt_username, error=f"Invalid request/user not found: {e}")
        await callback_query.answer(final_message, show_alert=True)
    except Exception as e: # Catch-all for other unexpected errors from the TeamTalk library or other issues
        logger.error("Generic error deleting TeamTalk user '%s' by admin %s: %s", tt_username, callback_query.from_user.id, e, exc_info=True)
        final_message = _("Failed to delete TeamTalk user '{tt_username}'. Reason: {error}").format(tt_username=tt_username, error=f"Unexpected error: {e}")
        await callback_query.answer(final_message, show_alert=True)

    try:
        await callback_query.message.edit_text(final_message, reply_markup=None)
    except Exception as e_edit:
        logger.debug("Failed to edit message after TT delete confirmation for user %s: %s", tt_username, e_edit)
        # The user already received an alert, so editing is for cleanup.
        # If it fails, it's not critical to send another message.


@router.message(Command("generate"))
async def generate_deeplink_handler(message: types.Message, bot: AiogramBot, db_session: AsyncSession):
    # Check if the user is an admin
    if message.from_user.id not in settings.admin_ids:
        logger.warning("User %s (not an admin) tried to use /generate.", message.from_user.id)
        # Optionally send a "permission denied" message if desired, or just return.
        # For now, just returning to avoid notifying non-admins about admin commands.
        return

    # Check if deeplink registration is enabled
    if not settings.telegram_deeplink_registration_enabled:
        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)
        await message.reply(_("Deeplink registration is currently disabled in the configuration."))
        return

    try:
        token = secrets.token_urlsafe(16)
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

        if not hasattr(bot, 'username') or not bot.username:
            logger.error("Bot username not found in cache. Cannot generate deeplink.")
            await message.reply(_("Internal error: bot username is not available. Please contact support."))
            return

        bot_username = bot.username
        deeplink_url = f"https://t.me/{bot_username}?start={token}"

        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)

        # Ensure the deeplink URL itself is not misinterpreted by MarkdownV2
        # by escaping any special Markdown characters within it if necessary,
        # though for a URL, this is usually not an issue with backticks.
        # For simplicity, assuming deeplink_url is safe for direct insertion into MarkdownV2 backticks.
        # Reply with only the deeplink URL formatted as code.
        reply_text = deeplink_url
        await message.reply(reply_text)
        logger.info("Admin %s generated deeplink: %s", acting_admin_id, deeplink_url)

    except Exception as e:
        logger.error("Error generating deeplink: %s", e, exc_info=True)
        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)
        await message.reply(_("An error occurred while generating the deeplink."))


logger.info("Admin router initialized with /generate command handler.")
