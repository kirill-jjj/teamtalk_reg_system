"""Admin command handlers."""
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import secrets

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import pytalk
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
from ..callbacks.admin_callbacks import (
    AdminBanListActionCallback,
    AdminDeleteCallback,
    AdminTTAccountsCallback,
)
from ..keyboards.admin_keyboards import (
    CALLBACK_DATA_DELETE_USER,
    get_admin_panel_keyboard,
)
from ..states import AdminActions

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("adminpanel"))
async def admin_panel_handler(message: types.Message) -> None:
    """Handles the /adminpanel command."""
    if message.from_user.id not in settings.admin_ids:
        logger.warning(
            "User %s (not an admin) tried to use /adminpanel.",
            message.from_user.id,
        )
        return

    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)
    reply_text = _("Admin Panel")

    keyboard = get_admin_panel_keyboard()
    await message.reply(reply_text, reply_markup=keyboard)


@router.message(Command("exit"))
async def exit_command_handler(
    message: types.Message, dispatcher: "Dispatcher"
) -> None:
    """Handles the /exit command to gracefully shut down the bot."""
    if message.from_user.id not in settings.admin_ids:
        logger.warning(
            "User %s (not an admin) tried to use /exit.", message.from_user.id
        )
        return

    logger.info("Admin %s initiated bot shutdown.", message.from_user.id)
    await message.reply("Shutting down...")
    await dispatcher.shutdown()


@router.callback_query(F.data == CALLBACK_DATA_DELETE_USER)
async def delete_user_start_handler(
    callback_query: types.CallbackQuery, db_session: AsyncSession
) -> None:
    """Handles the start of the user deletion process."""
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)
    if callback_query.from_user.id not in settings.admin_ids:
        logger.warning(
            "User %s (not an admin) tried to use delete user callback.",
            callback_query.from_user.id,
        )
        await callback_query.answer(
            _("Permission denied."), show_alert=True
        )
        return

    await callback_query.answer()

    users = await get_all_telegram_registrations(db_session)

    if not users:
        try:
            await callback_query.message.edit_text(
                _("No registered users found to delete.")
            )
        except Exception as e:
            logger.warning(
                "Could not edit message for no users found: %s", e
            )
            await callback_query.message.answer(
                _("No registered users found to delete.")
            )
        return

    builder = InlineKeyboardBuilder()
    for user in users:
        button_text = (
            f"TG ID: {user.telegram_id} - TT User: {user.teamtalk_username}"
        )
        callback_data = AdminDeleteCallback(user_telegram_id=user.telegram_id)
        builder.button(text=button_text, callback_data=callback_data)

    builder.adjust(1)

    reply_text = _("Select a user to delete:")
    try:
        await callback_query.message.edit_text(
            reply_text, reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.warning("Could not edit message to show user list: %s", e)
        await callback_query.message.answer(
            reply_text, reply_markup=builder.as_markup()
        )

    logger.info(
        "Admin %s requested user list for deletion.",
        callback_query.from_user.id,
    )


@router.callback_query(AdminDeleteCallback.filter())
async def confirm_delete_user_handler(
    callback_query: types.CallbackQuery,
    db_session: AsyncSession,
    callback_data: AdminDeleteCallback,
) -> None:
    """Handles the user deletion confirmation."""
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)
    if callback_query.from_user.id not in settings.admin_ids:
        logger.warning(
            "User %s (not an admin) tried to use confirm delete user callback.",
            callback_query.from_user.id,
        )
        await callback_query.answer(_("Permission denied."), show_alert=True)
        return

    telegram_id_to_delete = callback_data.user_telegram_id

    user_reg_stmt = select(TelegramRegistration).where(
        TelegramRegistration.telegram_id == telegram_id_to_delete
    )
    user_reg_result = await db_session.execute(user_reg_stmt)
    user_reg = user_reg_result.scalar_one_or_none()

    tt_username_for_ban: str | None = None
    if user_reg:
        tt_username_for_ban = user_reg.teamtalk_username
        logger.info(
            "Found TT username '%s' for TG ID %s before deletion.",
            tt_username_for_ban,
            telegram_id_to_delete,
        )
    else:
        logger.warning(
            "Could not find TG record for ID %s before deletion. "
            "Will ban without TT username.",
            telegram_id_to_delete,
        )

    deletion_successful = await delete_telegram_registration(
        db_session, telegram_id_to_delete
    )

    if deletion_successful:
        logger.info(
            "Admin %s successfully deleted TG record for ID: %s",
            callback_query.from_user.id,
            telegram_id_to_delete,
        )
        await add_banned_user(
            db_session=db_session,
            telegram_id=telegram_id_to_delete,
            teamtalk_username=tt_username_for_ban,
            admin_id=callback_query.from_user.id,
            reason="Deleted via bot admin panel",
        )
        logger.info(
            "User %s (TT: %s) also added to ban list by admin %s.",
            telegram_id_to_delete,
            tt_username_for_ban,
            callback_query.from_user.id,
        )
        reply_text = _(
            "User with Telegram ID {telegram_id} has been deleted and banned."
        ).format(telegram_id=telegram_id_to_delete)
    else:
        reply_text = _(
            "Failed to delete user with Telegram ID {telegram_id}."
        ).format(telegram_id=telegram_id_to_delete)
        logger.warning(
            "Admin %s failed to delete TG record for ID: %s. Ban not applied.",
            callback_query.from_user.id,
            telegram_id_to_delete,
        )

    await callback_query.answer(reply_text, show_alert=True)

    try:
        await callback_query.message.edit_text(reply_text, reply_markup=None)
    except Exception as e:
        logger.debug(
            "Could not edit message after deletion: %s. Alert was shown.", e
        )


# --- Ban List Management Handlers ---


async def _build_ban_list_message_and_keyboard(
    db_session: AsyncSession, _translator: "Callable[[str], str]"
) -> tuple[str, InlineKeyboardMarkup]:
    """Builds the message and keyboard for the ban list view."""
    banned_users = await get_banned_users(db_session)
    builder = InlineKeyboardBuilder()

    message_lines = [_translator("Banned Users:")]
    if not banned_users:
        message_lines.append(_translator("The ban list is empty."))
    else:
        for buser in banned_users:
            reason_text = buser.reason or "N/A"
            tt_user_text = buser.teamtalk_username or "N/A"
            tg_id_str = str(buser.telegram_id)
            message_lines.append(
                f"TG ID: {tg_id_str} - TT User: {tt_user_text} "
                f"(Reason: {reason_text})"
            )
            builder.button(
                text=f"{_translator('Unban')} ({tg_id_str})",
                callback_data=AdminBanListActionCallback(
                    action="unban", target_telegram_id=buser.telegram_id
                ).pack(),
            )

    builder.button(
        text=_translator("Add to Ban List Manually"),
        callback_data=AdminBanListActionCallback(
            action="add_prompt", target_telegram_id=None
        ).pack(),
    )
    builder.adjust(1)
    return "\n".join(message_lines), builder.as_markup()


@router.callback_query(AdminBanListActionCallback.filter(F.action == "view"))
async def view_ban_list_handler(
    callback_query: types.CallbackQuery, db_session: AsyncSession
) -> None:
    """Handles the view ban list callback."""
    await callback_query.answer()
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    message_text, reply_markup = await _build_ban_list_message_and_keyboard(
        db_session, _
    )
    try:
        await callback_query.message.edit_text(
            message_text, reply_markup=reply_markup
        )
    except Exception as e:
        logger.debug(
            "Failed to edit message for ban list view (no change or old): %s",
            e,
        )
        await callback_query.message.answer(
            message_text, reply_markup=reply_markup
        )


@router.callback_query(AdminBanListActionCallback.filter(F.action == "unban"))
async def unban_user_handler(
    callback_query: types.CallbackQuery,
    callback_data: AdminBanListActionCallback,
    db_session: AsyncSession,
) -> None:
    """Handles the unban user callback."""
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    target_id = callback_data.target_telegram_id
    if target_id is None:
        await callback_query.answer(
            _("Error: No target user ID specified for unban."),
            show_alert=True,
        )
        return

    success = await remove_banned_user(db_session, target_id)
    if success:
        alert_text = _(
            "User {target_telegram_id} has been unbanned."
        ).format(target_telegram_id=target_id)
        logger.info(
            "Admin %s unbanned user %s.", callback_query.from_user.id, target_id
        )
    else:
        alert_text = _(
            "Failed to unban user {target_telegram_id}."
        ).format(target_telegram_id=target_id)
        logger.warning(
            "Admin %s failed to unban user %s.",
            callback_query.from_user.id,
            target_id,
        )
    await callback_query.answer(alert_text, show_alert=True)

    message_text, reply_markup = await _build_ban_list_message_and_keyboard(
        db_session, _
    )
    try:
        await callback_query.message.edit_text(
            message_text, reply_markup=reply_markup
        )
    except Exception as e:
        logger.warning("Failed to refresh ban list after unban: %s", e)
        await callback_query.message.answer(
            text=_("Action processed. Could not refresh list immediately."),
        )


@router.callback_query(
    AdminBanListActionCallback.filter(F.action == "add_prompt")
)
async def manual_ban_prompt_handler(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    """Handles the manual ban prompt."""
    await callback_query.answer()
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)
    prompt_text = _(
        "Please enter the Telegram ID and reason for the ban on separate lines."
    )
    try:
        await callback_query.message.edit_text(prompt_text)
    except Exception as e:
        logger.debug("Could not edit message for manual ban prompt: %s", e)
        await callback_query.message.answer(prompt_text)
    await state.set_state(AdminActions.awaiting_manual_ban_id_reason)


@router.message(AdminActions.awaiting_manual_ban_id_reason, F.text)
async def process_manual_ban_handler(
    message: types.Message, state: FSMContext, db_session: AsyncSession
) -> None:
    """Handles the manual ban processing."""
    await state.clear()
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    parts = message.text.splitlines()
    if not parts:
        await message.reply(_("Invalid Telegram ID provided."))
        return

    telegram_id_str = parts[0].strip()
    reason = parts[1].strip() if len(parts) > 1 else None

    try:
        target_telegram_id = int(telegram_id_str)
        user_reg_stmt = select(TelegramRegistration.teamtalk_username).where(
            TelegramRegistration.telegram_id == target_telegram_id
        )
        user_reg_res = await db_session.execute(user_reg_stmt)
        tt_username = user_reg_res.scalar_one_or_none()

        await add_banned_user(
            db_session,
            telegram_id=target_telegram_id,
            teamtalk_username=tt_username,
            admin_id=message.from_user.id,
            reason=reason,
        )
        await message.reply(
            _("User {telegram_id} has been manually banned.").format(
                telegram_id=target_telegram_id
            )
        )
        logger.info(
            "Admin %s manually banned user %s with reason: '%s'. TT user: %s",
            message.from_user.id,
            target_telegram_id,
            reason,
            tt_username or "N/A",
        )
    except ValueError:
        logger.warning(
            "Admin %s provided invalid TG ID for manual ban: %s",
            message.from_user.id,
            telegram_id_str,
        )
        await message.reply(_("Invalid Telegram ID provided."))
    except Exception:
        logger.exception(
            "Failed to manually ban user %s by admin %s:",
            telegram_id_str,
            message.from_user.id,
        )
        await message.reply(
            _("Failed to manually ban user {telegram_id}.").format(
                telegram_id=telegram_id_str
            )
        )


# --- TeamTalk Account Listing Helpers ---


async def _get_pytalk_instance(
    pytalk_bot_instance: pytalk.TeamTalkBot,
) -> pytalk.TeamTalkInstance | None:
    """Gets the primary PyTalk instance and checks if it's connected."""
    if not pytalk_bot_instance.teamtalks:
        logger.warning("PyTalk instance list is empty.")
        return None

    tt_instance = pytalk_bot_instance.teamtalks[0]
    if (
        not tt_instance
        or not tt_instance.connected
        or not hasattr(tt_instance, "server")
    ):
        logger.warning("TeamTalk instance not available or not connected.")
        return None
    return tt_instance


async def _fetch_tt_accounts_from_server(
    tt_instance: pytalk.TeamTalkInstance,
) -> list[str] | None:
    """Fetches and decodes a list of usernames from the TeamTalk server."""
    try:
        user_accounts_sdk = await tt_instance.list_user_accounts()
        formatted_accounts = []
        if user_accounts_sdk:
            for acc_sdk in user_accounts_sdk:
                if hasattr(acc_sdk, "username"):
                    raw_username = acc_sdk.username
                    username_str = (
                        raw_username.decode("utf-8")
                        if isinstance(raw_username, bytes)
                        else str(raw_username)
                    )
                    formatted_accounts.append(username_str)
                else:
                    logger.warning(
                        "Found TT UserAccount object without 'username' attr: %s",
                        acc_sdk,
                    )
        logger.info(
            "Fetched %s accounts from TeamTalk server.",
            len(formatted_accounts),
        )
    except Exception:
        logger.exception("Error fetching TT accounts via list_user_accounts:")
        return None
    else:
        return formatted_accounts


async def _handle_tt_user_deletion(
    tt_instance: pytalk.TeamTalkInstance,
    tt_username: str,
    admin_id: int,
    _: Callable,
) -> str:
    """Performs the TT user deletion and returns a localized final message."""
    try:
        logger.info(
            "Admin %s requesting deletion of TeamTalk user: %s",
            admin_id,
            tt_username,
        )
        deletion_command_sent = tt_instance.delete_user_account(
            username=tt_username
        )

        if deletion_command_sent:
            logger.info(
                "Deletion command for '%s' sent successfully for admin %s.",
                tt_username,
                admin_id,
            )
            return _(
                "TeamTalk user '{tt_username}' was successfully deleted."
            ).format(tt_username=tt_username)
        logger.warning(
            "Deletion command for '%s' returned False for admin %s.",
            tt_username,
            admin_id,
        )
        return _(
            "Failed to delete TeamTalk user '{tt_username}'. Reason: {error}"
        ).format(
            tt_username=tt_username,
            error="Command indicated failure without a specific error.",
        )
    except PermissionError as e:
        logger.exception(
            "Permission error deleting TT user '%s':", tt_username
        )
        return _(
            "Failed to delete TeamTalk user '{tt_username}'. Reason: {error}"
        ).format(tt_username=tt_username, error=f"Permission denied: {e}")
    except ValueError as e:
        logger.exception(
            "Value error (e.g., user not found) deleting '%s':", tt_username
        )
        return _(
            "Failed to delete TeamTalk user '{tt_username}'. Reason: {error}"
        ).format(
            tt_username=tt_username,
            error=f"Invalid request/user not found: {e}",
        )
    except Exception:
        logger.exception("Generic error deleting TT user '%s':", tt_username)
        return _(
            "Failed to delete TeamTalk user '{tt_username}'. Reason: {error}"
        ).format(tt_username=tt_username, error="Unexpected error")


# --- TeamTalk Account Listing Handler ---


@router.callback_query(AdminTTAccountsCallback.filter(F.action == "list_all"))
async def list_all_tt_accounts_handler(
    pytalk_bot_instance: pytalk.TeamTalkBot,
    callback_query: types.CallbackQuery,
) -> None:
    """Handles the list all TeamTalk accounts callback."""
    await callback_query.answer()
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    tt_instance = await _get_pytalk_instance(pytalk_bot_instance)
    if not tt_instance:
        error_msg = _(
            "Could not connect to the TeamTalk server to get the list "
            "of accounts."
        )
        try:
            await callback_query.message.edit_text(error_msg, reply_markup=None)
        except Exception as e_edit:
            logger.debug("Failed to edit message for TT connection error: %s", e_edit)
            await callback_query.message.answer(error_msg, reply_markup=None)
        return

    user_accounts = await _fetch_tt_accounts_from_server(tt_instance)
    if user_accounts is None:
        error_msg = _(
            "Could not connect to the TeamTalk server to get the list "
            "of accounts."
        )
        try:
            await callback_query.message.edit_text(error_msg, reply_markup=None)
        except Exception as e_edit:
            logger.debug(
                "Failed to edit message for TT account fetching error: %s",
                e_edit,
            )
            await callback_query.message.answer(error_msg, reply_markup=None)
        return

    builder = InlineKeyboardBuilder()
    if not user_accounts:
        message_text = _("No TeamTalk accounts found on the server.")
    else:
        lines = [_("TeamTalk Accounts:")]
        for tt_username in user_accounts:
            lines.append(f"- {tt_username}")
            # The linter flags the next line as a potential SQL injection risk.
            # This is a false positive, as the f-string is used for a button
            # text in the UI, not for constructing an SQL query.
            builder.button(
                text=f"{_('Delete from TeamTalk')} ({tt_username})",  # noqa: S608
                callback_data=AdminTTAccountsCallback(
                    action="delete_prompt", tt_username=tt_username
                ).pack(),
            )
        message_text = "\n".join(lines)
    builder.adjust(1)

    try:
        await callback_query.message.edit_text(
            message_text,
            reply_markup=builder.as_markup() if user_accounts else None,
        )
    except Exception as e:
        logger.warning(
            "Failed to edit message for TT account list (no change/old): %s",
            e,
        )
        await callback_query.message.answer(
            message_text,
            reply_markup=builder.as_markup() if user_accounts else None,
        )


@router.callback_query(
    AdminTTAccountsCallback.filter(F.action == "delete_prompt")
)
async def prompt_delete_tt_account_handler(
    callback_query: types.CallbackQuery,
    callback_data: AdminTTAccountsCallback,
) -> None:
    """Handles the prompt for deleting a TeamTalk account."""
    await callback_query.answer()
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    tt_username = callback_data.tt_username
    if not tt_username:
        logger.warning(
            "prompt_delete_tt_account_handler: tt_username missing in cb."
        )
        error_text = _(
            "Error: Username not provided for deletion. Please try again."
        )
        try:
            await callback_query.message.edit_text(error_text, reply_markup=None)
        except Exception as e_edit:
            logger.debug(
                "Failed to edit message for missing tt_username error: %s",
                e_edit,
            )
            await callback_query.message.answer(error_text, reply_markup=None)
        return

    prompt_text = _(
        "Are you sure you want to delete the TeamTalk user '{tt_username}'?"
    ).format(tt_username=tt_username)

    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("Confirm Delete"),
        callback_data=AdminTTAccountsCallback(
            action="delete_confirm", tt_username=tt_username
        ).pack(),
    )
    builder.button(
        text=_("Cancel"),
        callback_data=AdminTTAccountsCallback(
            action="list_all", tt_username=None
        ).pack(),
    )
    builder.adjust(2)

    try:
        await callback_query.message.edit_text(
            prompt_text, reply_markup=builder.as_markup()
        )
    except Exception:
        logger.exception("Error editing message for TT delete prompt:")
        await callback_query.message.answer(
            prompt_text, reply_markup=builder.as_markup()
        )


@router.callback_query(
    AdminTTAccountsCallback.filter(F.action == "delete_confirm")
)
async def confirm_delete_tt_account_handler(
    pytalk_bot_instance: pytalk.TeamTalkBot,
    callback_query: types.CallbackQuery,
    callback_data: AdminTTAccountsCallback,
) -> None:
    """Handles the confirmation of deleting a TeamTalk account."""
    admin_lang = get_admin_lang_code()
    _ = get_translator(admin_lang)

    tt_username = callback_data.tt_username
    if not tt_username:
        logger.error(
            "confirm_delete: tt_username missing in callback_data."
        )
        await callback_query.answer(
            _("Error: Username missing. Cannot delete."), show_alert=True
        )
        try:
            await callback_query.message.edit_text(
                _("Internal error: Username was not provided for deletion."),
            )
        except Exception as e_edit:
            logger.debug(
                "Failed to edit message for missing tt_username on confirm: %s",
                e_edit,
            )
        return

    tt_instance = await _get_pytalk_instance(pytalk_bot_instance)
    if not tt_instance:
        error_msg = _(
            "Could not connect to the TeamTalk server to delete the account."
        )
        await callback_query.answer(error_msg, show_alert=True)
        try:
            await callback_query.message.edit_text(error_msg, reply_markup=None)
        except Exception as e_edit:
            logger.debug(
                "Failed to edit message for TT connection error on confirm: %s",
                e_edit,
            )
            await callback_query.message.answer(error_msg, reply_markup=None)
        return

    final_message = await _handle_tt_user_deletion(
        tt_instance, tt_username, callback_query.from_user.id, _
    )
    await callback_query.answer(final_message, show_alert=True)

    try:
        await callback_query.message.edit_text(final_message, reply_markup=None)
    except Exception as e_edit:
        logger.debug(
            "Failed to edit message after TT delete confirmation for %s: %s",
            tt_username,
            e_edit,
        )


@router.message(Command("generate"))
async def generate_deeplink_handler(
    message: types.Message, bot: AiogramBot, db_session: AsyncSession
) -> None:
    """Handles the /generate command."""
    if message.from_user.id not in settings.admin_ids:
        logger.warning(
            "User %s (not an admin) tried to use /generate.",
            message.from_user.id,
        )
        return

    if not settings.telegram_deeplink_registration_enabled:
        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)
        await message.reply(
            _("Deeplink registration is currently disabled in the configuration.")
        )
        return

    try:
        token = secrets.token_urlsafe(16)
        token_expiry_minutes = 5
        expires_at = datetime.now(datetime.UTC) + timedelta(
            minutes=token_expiry_minutes
        )
        acting_admin_id = message.from_user.id

        await create_deeplink_token(
            db_session,
            token_str=token,
            expires_at=expires_at,
            generated_by_admin_id=acting_admin_id,
        )

        if not hasattr(bot, "username") or not bot.username:
            logger.error("Bot username not found. Cannot generate deeplink.")
            await message.reply(
                _(
                    "Internal error: bot username is not available. "
                    "Please contact support."
                )
            )
            return

        bot_username = bot.username
        deeplink_url = f"https://t.me/{bot_username}?start={token}"

        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)

        await message.reply(deeplink_url)
        logger.info(
            "Admin %s generated deeplink: %s", acting_admin_id, deeplink_url
        )

    except Exception:
        logger.exception("Error generating deeplink:")
        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)
        await message.reply(
            _("An error occurred while generating the deeplink.")
        )


logger.info("Admin router initialized with /generate command handler.")
