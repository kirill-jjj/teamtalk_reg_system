import logging
import uuid
from typing import Any

from aiogram import Bot as AiogramBot
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pytalk.enums import UserType as PyTalkUserType
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db import add_pending_telegram_registration, add_telegram_registration
from ...core.localization import get_admin_lang_code, get_translator
from ...teamtalk import users as tt_users_service
from ...utils.schemas import TTConnectionInfo, TTUserInfo
from ...utils.file_generator import generate_tt_file_content, generate_tt_link
from ..schemas import RegistrationStateData
from ..states import RegistrationStates
from .reg_callback_data import AdminVerificationCallback, NicknameChoiceCallback

logger = logging.getLogger(__name__)


async def _ask_nickname_preference(
    message_target: types.Message | types.CallbackQuery,
    state: FSMContext,
    username_value: str,
    user_lang_code: str,
):
    _ = get_translator(user_lang_code)
    yes_button_text = _("Yes")
    no_button_text = _("No (use username)")

    builder = InlineKeyboardBuilder()
    builder.button(text=yes_button_text, callback_data=NicknameChoiceCallback(action="provide"))
    builder.button(text=no_button_text, callback_data=NicknameChoiceCallback(action="generate"))
    builder.adjust(1)

    prompt_message = _(
        "Your username will be '{username}'. Would you like to set a different nickname? If not, your nickname will be the same as your username."
    ).format(username=username_value)

    if isinstance(message_target, types.Message):
        await message_target.reply(prompt_message, reply_markup=builder.as_markup())
    elif isinstance(message_target, types.CallbackQuery):
        await message_target.answer()
        await message_target.message.answer(prompt_message, reply_markup=builder.as_markup())
        try:
            await message_target.message.delete()
        except Exception as e:
            logger.debug(f"Could not delete message before asking nickname preference: {e}")

    await state.set_state(RegistrationStates.awaiting_nickname_choice)


async def _send_tt_credentials_to_user(
    bot: AiogramBot,
    user_id_val: int,
    user_lang_code: str,
    artefact_data: dict[str, Any],  # This comes from teamtalk_service, can be refactored later
):
    _ = get_translator(user_lang_code)

    connection_info = TTConnectionInfo(
        server_name=artefact_data["server_name"],
        host=artefact_data["effective_hostname"],
        tcpport=artefact_data["tcp_port"],
        udpport=artefact_data["udp_port"],
        encrypted=artefact_data["encrypted"],
    )
    user_info = TTUserInfo(
        username=artefact_data["username"],
        password=artefact_data["password"],
        nickname=artefact_data["final_nickname"],
    )

    tt_file_content_str = generate_tt_file_content(connection_info, user_info)
    tt_link_str = generate_tt_link(connection_info, user_info)

    tt_file_bytes = bytes(tt_file_content_str, encoding="utf-8")
    server_name_for_file = artefact_data["server_name"]
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
    except Exception as e_send:
        logger.error(
            f"Error sending .tt file or link to user {user_id_val}: {e_send}",
            exc_info=True,
        )
        await bot.send_message(
            user_id_val, _("Could not send the .tt file or link. Please contact an admin.")
        )


async def _process_actual_registration(
    db_session: AsyncSession,
    state_data: RegistrationStateData,
    source_info: dict,  # The dict passed to TT server
    state: FSMContext | None,
    bot: AiogramBot,
):
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

    registrant_user_id = state_data.registrant_telegram_id
    if success:
        await bot.send_message(
            registrant_user_id,
            _("User {username} successfully registered.").format(username=state_data.name),
        )

        initiator_telegram_id = source_info.get("registrar_telegram_id")
        if not state_data.is_admin_registrar or (
            state_data.is_admin_registrar and initiator_telegram_id == registrant_user_id
        ):
            try:
                registration_record = await add_telegram_registration(
                    db_session, registrant_user_id, state_data.name
                )
                if registration_record is None:
                    logger.info(
                        f"Telegram registration for admin ID {registrant_user_id} (username: {state_data.name}) was intentionally skipped."
                    )
            except Exception as e_db_add:
                logger.error(
                    f"CRITICAL DB Exception for TT user {state_data.name} (TG ID: {registrant_user_id}): {e_db_add}",
                    exc_info=True,
                )
                await bot.send_message(
                    registrant_user_id,
                    _(
                        "Your TeamTalk account is ready, but there was an issue syncing your registration locally. Please contact an administrator if you experience issues."
                    ),
                )
                for admin_tg_id_notify in settings.admin_ids:
                    if admin_tg_id_notify != registrant_user_id:
                        await bot.send_message(
                            admin_tg_id_notify,
                            f"DB SYNC ERROR (Exception): User {state_data.name} (TG ID: {registrant_user_id}) created in TeamTalk but FAILED local DB save. Exception: {e_db_add}",
                        )

        if settings.admin_ids:
            _ = get_translator(get_admin_lang_code())
            admin_notification_message = (
                f"📢 {_('User {username} was registered.').format(username=state_data.name)}\n"
            )
            lang_code_for_emoji = state_data.selected_language or "en"
            lang_emoji = (
                "🇬🇧" if lang_code_for_emoji == "en" else ("🇷🇺" if lang_code_for_emoji == "ru" else "❓")
            )
            admin_notification_message += (
                _("👤 Client language: {lang_emoji}").format(lang_emoji=lang_emoji) + "\n"
            )
            tg_full_name = source_info.get("telegram_full_name", "N/A")
            admin_notification_message += (
                _("📱 Via Telegram: {telegram_full_name} (ID: {registrant_telegram_id})").format(
                    telegram_full_name=tg_full_name,
                    registrant_telegram_id=registrant_user_id,
                )
                + "\n"
            )
            if (
                state_data.is_admin_registrar
                and initiator_telegram_id != registrant_user_id
            ):
                admin_notification_message += (
                    _("🔑 Registered by Admin ID: {initiator_telegram_id}").format(
                        initiator_telegram_id=initiator_telegram_id
                    )
                    + "\n"
                )

            for admin_id_val_notify in settings.admin_ids:
                try:
                    await bot.send_message(
                        admin_id_val_notify, admin_notification_message.strip()
                    )
                except Exception as e_notify:
                    logger.error(
                        f"Failed to send admin reg notification to {admin_id_val_notify}: {e_notify}"
                    )

        if artefact_data_val:
            await _send_tt_credentials_to_user(
                bot, registrant_user_id, user_lang_code, artefact_data_val
            )
    else:
        logger.error(
            f"TT Registration failed for {state_data.name}. Detail: {reg_msg_key_or_detail}"
        )
        await bot.send_message(
            registrant_user_id,
            _("Registration error. Please try again later or contact an administrator."),
        )

    if state:
        await state.clear()
    return success, reg_msg_key_or_detail, artefact_data_val


async def _handle_registration_continuation(
    db_session: AsyncSession,
    state: FSMContext,
    bot: AiogramBot,
    message_or_callback_query: types.Message | types.CallbackQuery,
):
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {{}})

    user_object = message_or_callback_query.from_user
    user_full_name = user_object.full_name
    telegram_username = user_object.username

    source_info = {
        "type": "telegram",
        "telegram_id": state_data.registrant_telegram_id,
        "telegram_full_name": user_full_name,
        "telegram_username": telegram_username,
        "selected_language": state_data.selected_language,
        "nickname": state_data.nickname,
        "is_admin_registrar": state_data.is_admin_registrar,
        "tt_account_type": state_data.tt_account_type,
        "registrar_telegram_id": user_object.id,
    }

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
                f"Reg request {current_request_key} for TG user {state_data.registrant_telegram_id} ({state_data.name}) stored in DB for admin verification."
            )
        except Exception as e_db_add_pending:
            logger.error(
                f"Failed to add pending registration to DB for user {state_data.registrant_telegram_id}, username {state_data.name}: {e_db_add_pending}",
                exc_info=True,
            )
            await bot.send_message(
                state_data.registrant_telegram_id,
                _(
                    "An error occurred while submitting your registration for approval. Please try again later or contact an administrator."
                ),
            )
            if state:
                await state.clear()
            return

        _ = get_translator(get_admin_lang_code())
        admin_msg_text = (
            _("Registration request:") + "\n" + _("Username:") + f" {state_data.name}\n"
        )
        if state_data.nickname != state_data.name:
            admin_msg_text += _("Nickname:") + f" {state_data.nickname}\n"

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
            except Exception as e:
                logger.error(
                    f"Error sending verification to admin {admin_id}: {e}", exc_info=True
                )

        reply_text = _("Registration request sent to administrators. Please wait for approval.")
        if isinstance(message_or_callback_query, types.Message):
            await message_or_callback_query.answer(reply_text)
        elif isinstance(message_or_callback_query, types.CallbackQuery):
            await message_or_callback_query.message.answer(reply_text)

        await state.set_state(RegistrationStates.waiting_admin_approval)
    else:
        if state_data.is_admin_registrar:
            logger.info(
                f"Admin {user_object.id} bypassing admin verification for user {state_data.name} (registrant_id: {state_data.registrant_telegram_id})."
            )

        await _process_actual_registration(
            db_session=db_session,
            state_data=state_data,
            source_info=source_info,
            state=state,
            bot=bot,
        )


logger.info("Registration logic helpers configured.")