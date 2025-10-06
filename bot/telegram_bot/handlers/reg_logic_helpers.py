"""This module contains helper functions for the registration logic."""
import logging
import uuid

from aiogram import Bot as AiogramBot
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
import pytalk  # New import
from pytalk.enums import UserType as PyTalkUserType
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db import add_pending_telegram_registration, add_telegram_registration
from ...core.localization import get_admin_lang_code, get_translator
from ...teamtalk import users as tt_users_service
from ...utils.file_generator import generate_tt_file_content, generate_tt_link
from ...utils.schemas import (
    TeamTalkRegistrationArtefacts,
    TelegramSourceInfo,
    TTConnectionInfo,
    TTUserInfo,
)
from ..schemas import RegistrationStateData
from ..states import RegistrationStates
from .reg_callback_data import AdminVerificationCallback, NicknameChoiceCallback

logger = logging.getLogger(__name__)


async def _ask_nickname_preference(
    message_target: types.Message | types.CallbackQuery,
    state: FSMContext,
    username_value: str,
    user_lang_code: str,
) -> None:
    _ = get_translator(user_lang_code)
    yes_button_text = _("Yes")
    no_button_text = _("No (use username)")

    builder = InlineKeyboardBuilder()
    builder.button(
        text=yes_button_text, callback_data=NicknameChoiceCallback(action="provide")
    )
    builder.button(
        text=no_button_text, callback_data=NicknameChoiceCallback(action="generate")
    )
    builder.adjust(1)

    prompt_message = _(
        "Your username will be '{username}'. Would you like to set a different "
        "nickname? If not, your nickname will be the same as your username."
    ).format(username=username_value)

    if isinstance(message_target, types.Message):
        await message_target.reply(prompt_message, reply_markup=builder.as_markup())
    elif isinstance(message_target, types.CallbackQuery):
        await message_target.answer()
        await message_target.message.answer(
            prompt_message, reply_markup=builder.as_markup()
        )
        try:
            await message_target.message.delete()
        except Exception as e:
            logger.debug(
                "Could not delete message before asking nickname preference: %s", e
            )

    await state.set_state(RegistrationStates.awaiting_nickname_choice)


async def _send_tt_credentials_to_user(
    bot: AiogramBot,
    user_id_val: int,
    user_lang_code: str,
    artefact_data: TeamTalkRegistrationArtefacts,  # This comes from teamtalk_service,
) -> None:
    """Sends the .tt file and connection link to the user."""
    _ = get_translator(user_lang_code)

    connection_info = TTConnectionInfo(
        server_name=artefact_data.server_name,
        host=artefact_data.effective_hostname,
        tcpport=artefact_data.tcp_port,
        udpport=artefact_data.udp_port,
        encrypted=artefact_data.encrypted,
    )
    user_info = TTUserInfo(
        username=artefact_data.username,
        password=artefact_data.password,
        nickname=artefact_data.final_nickname,
    )

    tt_file_content_str = generate_tt_file_content(connection_info, user_info)
    tt_link_str = generate_tt_link(connection_info, user_info)

    tt_file_bytes = bytes(tt_file_content_str, encoding="utf-8")
    server_name_for_file = artefact_data.server_name
    safe_server_name = "".join(
        c if c.isalnum() or c in (" ", "_", "-") else "_" for c in server_name_for_file
    ).rstrip()
    if not safe_server_name:
        safe_server_name = "TeamTalk_Server"
    generated_filename = f"{safe_server_name}.tt"
    tt_buffered_file = BufferedInputFile(tt_file_bytes, filename=generated_filename)

    try:
        await bot.send_document(
            user_id_val,
            document=tt_buffered_file,
            caption=_("Your .tt file for quick connection"),
        )
        link_text_part = _("Or use this TT link:\n")
        message_content = f"{link_text_part}`{tt_link_str}`"
        await bot.send_message(user_id_val, message_content, parse_mode="Markdown")
    except Exception:
        logger.exception(
            "Error sending .tt file or link to user %s:",
            user_id_val,
        )
        await bot.send_message(
            user_id_val,
            _("Could not send the .tt file or link. Please contact an admin."),
        )


async def _handle_successful_registration_actions(
    bot: AiogramBot,
    db_session: AsyncSession,
    state_data: RegistrationStateData,
    source_info: dict,
    artefact_data_val: TeamTalkRegistrationArtefacts,
    user_lang_code: str,
) -> None:
    """Handles actions after a successful TeamTalk registration."""
    _ = get_translator(user_lang_code)
    registrant_user_id = state_data.registrant_telegram_id

    await bot.send_message(
        registrant_user_id,
        _("User {username} successfully registered.").format(
            username=state_data.name
        ),
    )

    initiator_telegram_id = source_info.get("registrar_telegram_id")
    if not state_data.is_admin_registrar or (
        state_data.is_admin_registrar
        and initiator_telegram_id == registrant_user_id
    ):
        try:
            registration_record = await add_telegram_registration(
                db_session, registrant_user_id, state_data.name
            )
            if registration_record is None:
                logger.info(
                    "Telegram registration for admin ID %s (username: %s) "
                    "was intentionally skipped.",
                    registrant_user_id,
                    state_data.name,
                )
        except Exception as e_db_add:
            logger.exception(
                "CRITICAL DB Exception for TT user %s (TG ID: %s):",
                state_data.name,
                registrant_user_id,
                exc_info=e_db_add,
            )
            await bot.send_message(
                registrant_user_id,
                _(
                    "Your TeamTalk account is ready, but there was an issue "
                    "syncing your registration locally. Please contact an "
                    "administrator if you experience issues."
                ),
            )
            for admin_tg_id_notify in settings.admin_ids:
                if admin_tg_id_notify != registrant_user_id:
                    await bot.send_message(
                        admin_tg_id_notify,
                        "DB SYNC ERROR (Exception): User %s (TG ID: %s) "
                        "created in TeamTalk but FAILED local DB save. "
                        "Exception: %s",
                        state_data.name,
                        registrant_user_id,
                        exc_info=e_db_add,
                    )

    if settings.admin_ids:
        _ = get_translator(get_admin_lang_code())
        admin_notification_message = _(
            "📢 User {username} was registered.\n"
        ).format(username=state_data.name)
        lang_code_for_emoji = state_data.selected_language or "en"
        lang_emoji = (
            "🇬🇧"
            if lang_code_for_emoji == "en"
            else ("🇷🇺" if lang_code_for_emoji == "ru" else "❓")
        )
        admin_notification_message += _("👤 Client language: {lang_emoji}\n").format(
            lang_emoji=lang_emoji
        )
        tg_full_name = source_info.get("telegram_full_name", "N/A")
        admin_notification_message += _(
            "📱 Via Telegram: {telegram_full_name} (ID: {registrant_telegram_id})\n"
        ).format(
            telegram_full_name=tg_full_name,
            registrant_telegram_id=registrant_user_id,
        )
        if (
            state_data.is_admin_registrar
            and initiator_telegram_id != registrant_user_id
        ):
            admin_notification_message += _(
                "🔑 Registered by Admin ID: {initiator_telegram_id}\n"
            ).format(initiator_telegram_id=initiator_telegram_id)

        for admin_id_val_notify in settings.admin_ids:
            try:
                await bot.send_message(
                    admin_id_val_notify, admin_notification_message.strip()
                )
            except Exception as e_notify:
                logger.exception(
                    "Error sending admin reg notification to %s:",
                    admin_id_val_notify,
                    exc_info=e_notify,
                )

    if artefact_data_val:
        await _send_tt_credentials_to_user(
            bot, registrant_user_id, user_lang_code, artefact_data_val
        )


async def _process_actual_registration(
    pytalk_bot_instance: pytalk.TeamTalkBot,  # New argument
    db_session: AsyncSession,
    state_data: RegistrationStateData,
    source_info: dict,
    state: FSMContext | None,
    bot: AiogramBot,
) -> tuple[bool, str | None, TeamTalkRegistrationArtefacts | None]:
    """Processes and notifies about TeamTalk registration."""
    user_lang_code = state_data.selected_language or settings.bot_admin_lang
    _ = get_translator(user_lang_code)

    tt_usertype_for_sdk = PyTalkUserType.DEFAULT
    if state_data.is_admin_registrar and state_data.tt_account_type == "admin":
        tt_usertype_for_sdk = PyTalkUserType.ADMIN

    broadcast_text_for_tt = None
    if settings.teamtalk_registration_broadcast_enabled:
        admin_lang_translator = get_translator(get_admin_lang_code())
        broadcast_text_for_tt = admin_lang_translator(
            "User {username} was registered."
        ).format(username=state_data.name)

    (
        success,
        reg_msg_key_or_detail,
        artefact_data_val,
    ) = await tt_users_service.perform_teamtalk_registration(
        pytalk_bot_instance,  # New argument
        username_str=state_data.name,
        password_str=state_data.password,
        usertype_to_create=tt_usertype_for_sdk,
        nickname_str=state_data.nickname,
        source_info=source_info,
        broadcast_message_text=broadcast_text_for_tt,
        teamtalk_default_user_rights=settings.teamtalk_default_user_rights,
        registration_broadcast_enabled=settings.teamtalk_registration_broadcast_enabled,
        host_name=settings.host_name,
        tcp_port=settings.port,
        udp_port=settings.udp_port,
        encrypted=settings.encrypted,
        server_name=settings.server_name,
        teamtalk_public_hostname=settings.tt_public_hostname,
    )

    if success:
        await _handle_successful_registration_actions(
            bot, db_session, state_data, source_info, artefact_data_val, user_lang_code
        )
    else:
        registrant_user_id = state_data.registrant_telegram_id
        logger.error(
            "TT Registration failed for %s. Detail: %s",
            state_data.name,
            reg_msg_key_or_detail,
        )
        await bot.send_message(
            registrant_user_id,
            _(
                "Registration error. Please try again later or contact an "
                "administrator."
            ),
        )

    if state:
        await state.clear()
    return success, reg_msg_key_or_detail, artefact_data_val


async def _handle_registration_continuation(
    pytalk_bot_instance: pytalk.TeamTalkBot,  # New argument
    db_session: AsyncSession,
    state: FSMContext,
    bot: AiogramBot,
    message_or_callback_query: types.Message | types.CallbackQuery,
) -> None:
    """Handles the continuation of the registration process."""
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {{}})

    user_object = message_or_callback_query.from_user
    user_full_name = user_object.full_name
    telegram_username = user_object.username

    source_info = TelegramSourceInfo(
        telegram_id=state_data.registrant_telegram_id,
        telegram_full_name=user_full_name,
        telegram_username=telegram_username,
        selected_language=state_data.selected_language,
        nickname=state_data.nickname,
        is_deeplink_registration=state_data.is_deeplink_registration,
        is_admin_registrar=state_data.is_admin_registrar,
        tt_account_type=state_data.tt_account_type,
        registrar_telegram_id=user_object.id,
    )
    _ = get_translator(state_data.selected_language or settings.bot_admin_lang)

    if settings.verify_registration and not state_data.is_admin_registrar:
        current_request_key = uuid.uuid4().hex
        try:
            await add_pending_telegram_registration(
                db=db_session,
                request_key=current_request_key,
                registrant_telegram_id=state_data.registrant_telegram_id,
                username=state_data.name,
                password_cleartext=state_data.password,
                nickname=state_data.nickname,
                source_info=source_info,
            )
            logger.info(
                "Reg request %s for TG user %s (%s) stored in DB for admin "
                "verification.",
                current_request_key,
                state_data.registrant_telegram_id,
                state_data.name,
            )
        except Exception:
            logger.exception(
                "Failed to add pending registration to DB for user %s, username %s:",
                state_data.registrant_telegram_id,
                state_data.name,
            )
            await bot.send_message(
                state_data.registrant_telegram_id,
                _(
                    "An error occurred while submitting your registration for "
                    "approval. Please try again later or contact an "
                    "administrator."
                ),
            )
            if state:
                await state.clear()
            return

        admin_lang_translator = get_translator(get_admin_lang_code())
        admin_msg_text = admin_lang_translator(
            "Registration request:\nUsername: {username}\n"
        ).format(username=state_data.name)
        if state_data.nickname != state_data.name:
            admin_msg_text += admin_lang_translator(
                "Nickname: {nickname}\n"
            ).format(nickname=state_data.nickname)

        telegram_user_info_line = f" {user_full_name}"
        if telegram_username:
            telegram_user_info_line += f" (@{telegram_username})"
        telegram_user_info_line += f" (ID: {state_data.registrant_telegram_id})"

        admin_msg_text += (
            _("Telegram User:")
            + telegram_user_info_line
            + "\n"
            + _("Approve registration?")
        )

        builder = InlineKeyboardBuilder()
        builder.button(
            text=_("Yes"),
            callback_data=AdminVerificationCallback(
                action="verify", request_key=current_request_key
            ),
        )
        builder.button(
            text=_("No"),
            callback_data=AdminVerificationCallback(
                action="reject", request_key=current_request_key
            ),
        )
        builder.adjust(2)

        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(
                    admin_id, admin_msg_text, reply_markup=builder.as_markup()
                )
            except Exception:
                logger.exception(
                    "Error sending verification to admin %s:", admin_id
                )

        reply_text = _(
            "Registration request sent to administrators. Please wait for approval."
        )
        if isinstance(message_or_callback_query, types.Message):
            await message_or_callback_query.answer(reply_text)
        elif isinstance(message_or_callback_query, types.CallbackQuery):
            await message_or_callback_query.message.answer(reply_text)

        await state.set_state(RegistrationStates.waiting_admin_approval)
    else:
        if state_data.is_admin_registrar:
            logger.info(
                "Admin %s bypassing admin verification for user %s "
                "(registrant_id: %s).",
                user_object.id,
                state_data.name,
                state_data.registrant_telegram_id,
            )

        await _process_actual_registration(
            pytalk_bot_instance,  # New argument
            db_session=db_session,
            state_data=state_data,
            source_info=source_info.model_dump(exclude_unset=True),
            state=state,
            bot=bot,
        )


async def _notify_admins_about_decision(
    bot: AiogramBot,
    acting_admin_id: int,
    acting_admin_name: str,
    registrant_telegram_id: int,
    registrant_tg_username: str | None,
    teamtalk_username: str,
    decision: str,  # "approved" or "rejected"
) -> None:
    """Notifies all administrators about a registration decision."""
    _ = get_translator(get_admin_lang_code())

    decision_text = _("approved") if decision == "approved" else _("rejected")
    notification_message = _(
        "Admin {admin_name} ({admin_id}) has {decision_text} the registration "
        "request for TeamTalk user '{teamtalk_username}' "
        "(Telegram ID: {registrant_telegram_id})."
    ).format(
        admin_name=acting_admin_name,
        admin_id=acting_admin_id,
        decision_text=decision_text,
        teamtalk_username=teamtalk_username,
        registrant_telegram_id=registrant_telegram_id,
    )

    if registrant_tg_username:
        notification_message += _(
            " Telegram Username: @{registrant_tg_username}"
        ).format(registrant_tg_username=registrant_tg_username)

    for admin_id in settings.admin_ids:
        if admin_id != acting_admin_id:  # Don't send to the admin who made the decision
            try:
                await bot.send_message(admin_id, notification_message)
            except Exception:
                logger.exception(
                    "Failed to send admin notification to %s about "
                    "registration decision:",
                    admin_id,
                )

logger.info("Registration logic helpers configured.")
