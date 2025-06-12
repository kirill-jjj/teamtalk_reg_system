import logging
from typing import Dict, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Bot as AiogramBot, types
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ...core import config
from ...core.db import add_telegram_registration
from ...teamtalk import users as tt_users_service
from ...core.localization import get_admin_lang_code, get_translator
from ...utils.file_generator import generate_tt_file_content, generate_tt_link
from ..states import RegistrationStates
from pytalk.enums import UserType as PyTalkUserType

# Updated import to point to reg_callback_data.py
from .reg_callback_data import AdminVerificationCallback, NicknameChoiceCallback

logger = logging.getLogger(__name__)

registration_requests: Dict[int, Dict] = {}
request_id_counter = 0

async def _ask_nickname_preference(
    message_target: types.Message | types.CallbackQuery,
    state: FSMContext,
    username_value: str,
    user_lang_code: str
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
    artefact_data: Dict[str, Any]
):
    _ = get_translator(user_lang_code)

    tt_file_content_str = generate_tt_file_content(
        server_name_val=artefact_data["server_name"],
        host_val=artefact_data["effective_hostname"],
        tcpport_val=artefact_data["tcp_port"],
        udpport_val=artefact_data["udp_port"],
        encrypted_val=artefact_data["encrypted"],
        username_val=artefact_data["username"],
        password_val=artefact_data["password"],
        nickname_val=artefact_data["final_nickname"]
    )
    tt_link_str = generate_tt_link(
        host_val=artefact_data["effective_hostname"],
        tcpport_val=artefact_data["tcp_port"],
        udpport_val=artefact_data["udp_port"],
        encrypted_val=artefact_data["encrypted"],
        username_val=artefact_data["username"],
        password_val=artefact_data["password"],
        nickname_val=artefact_data["final_nickname"]
    )

    tt_file_bytes = bytes(tt_file_content_str, encoding="utf-8")
    server_name_for_file = artefact_data["server_name"]
    safe_server_name = "".join(
        c if c.isalnum() or c in (" ", "_", "-") else "_" for c in server_name_for_file
    ).rstrip()
    if not safe_server_name: safe_server_name = "TeamTalk_Server"
    generated_filename = f"{safe_server_name}.tt"
    tt_buffered_file = BufferedInputFile(tt_file_bytes, filename=generated_filename)

    try:
        await bot.send_document(user_id_val, document=tt_buffered_file, caption=_("Your .tt file for quick connection"))
        link_text_part = _("Or use this TT link:\n")
        message_content = f"{link_text_part}`{tt_link_str}`"
        await bot.send_message(user_id_val, message_content, parse_mode="Markdown")
    except Exception as e_send:
        logger.error(f"Error sending .tt file or link to user {user_id_val}: {e_send}", exc_info=True)
        await bot.send_message(user_id_val, _("Could not send the .tt file or link. Please contact an admin."))

async def _process_actual_registration(
    db_session: AsyncSession,
    registrant_user_id: int,
    username_val: str,
    password_val_reg: str,
    nickname_val: str,
    source_info: Dict,
    state: Optional[FSMContext],
    bot: AiogramBot,
):
    user_lang_code = source_info.get("selected_language", config.CFG_ADMIN_LANG)
    _ = get_translator(user_lang_code)

    if "nickname" not in source_info: source_info["nickname"] = nickname_val

    is_initiator_admin = source_info.get("is_admin_registrar", False)
    tt_account_type_chosen = source_info.get("tt_account_type")

    tt_usertype_for_sdk = PyTalkUserType.DEFAULT
    if is_initiator_admin and tt_account_type_chosen == "admin":
        tt_usertype_for_sdk = PyTalkUserType.ADMIN

    broadcast_text_for_tt = None
    if config.REGISTRATION_BROADCAST_ENABLED:
        admin_lang_translator = get_translator(get_admin_lang_code())
        broadcast_text_for_tt = admin_lang_translator("User {} was registered.").format(username_val)

    success, reg_msg_key_or_detail, artefact_data_val = await tt_users_service.perform_teamtalk_registration(
        username_str=username_val,
        password_str=password_val_reg,
        usertype_to_create=tt_usertype_for_sdk,
        nickname_str=nickname_val,
        source_info=source_info,
        broadcast_message_text=broadcast_text_for_tt,
        teamtalk_default_user_rights=config.TEAMTALK_DEFAULT_USER_RIGHTS,
        registration_broadcast_enabled=config.REGISTRATION_BROADCAST_ENABLED,
        host_name=config.HOST_NAME,
        tcp_port=config.TCP_PORT,
        udp_port=config.UDP_PORT,
        encrypted=config.ENCRYPTED,
        server_name=config.SERVER_NAME,
        teamtalk_public_hostname=config.TEAMTALK_PUBLIC_HOSTNAME
    )

    if success:
        await bot.send_message(registrant_user_id, _("User {} successfully registered.").format(username_val))

        initiator_telegram_id = source_info.get("registrar_telegram_id")
        if not is_initiator_admin or (is_initiator_admin and initiator_telegram_id == registrant_user_id):
            try:
                await add_telegram_registration(db_session, registrant_user_id, username_val)
            except Exception as e_db_add:
                logger.error(f"CRITICAL DB Exception for TT user {username_val} (TG ID: {registrant_user_id}): {e_db_add}", exc_info=True)
                await bot.send_message(registrant_user_id, _("Registration completed, but a sync error occurred. Please contact admin."))
                for admin_tg_id_notify in config.ADMIN_IDS:
                    await bot.send_message(admin_tg_id_notify, f"DB SYNC ERROR (Exception): User {username_val} (TG ID: {registrant_user_id}) registered on TT but FAILED local DB save. Exc: {e_db_add}")

        if config.ADMIN_IDS:
            admin_notify_lang = get_translator(get_admin_lang_code())
            admin_notification_message = f"📢 {admin_notify_lang('User {} was registered.').format(username_val)}\n"
            lang_code_for_emoji = source_info.get('selected_language', 'en')
            lang_emoji = "🇬🇧" if lang_code_for_emoji == 'en' else ("🇷🇺" if lang_code_for_emoji == 'ru' else "❓")
            admin_notification_message += admin_notify_lang("👤 Client language: {}").format(lang_emoji) + "\n"
            tg_full_name = source_info.get('telegram_full_name', 'N/A')
            admin_notification_message += admin_notify_lang("📱 Via Telegram: {} (ID: {})").format(tg_full_name, registrant_user_id) + "\n"
            if is_initiator_admin and initiator_telegram_id != registrant_user_id:
                 admin_notification_message += admin_notify_lang("🔑 Registered by Admin ID: {}").format(initiator_telegram_id) + "\n"

            for admin_id_val_notify in config.ADMIN_IDS:
                try: await bot.send_message(admin_id_val_notify, admin_notification_message.strip())
                except Exception as e_notify: logger.error(f"Failed to send admin reg notification to {admin_id_val_notify}: {e_notify}")

        if artefact_data_val:
            await _send_tt_credentials_to_user(bot, registrant_user_id, user_lang_code, artefact_data_val)
    else:
        logger.error(f"TT Registration failed for {username_val}. Detail: {reg_msg_key_or_detail}")
        await bot.send_message(registrant_user_id, _("Registration error. Please try again later or contact an administrator."))

    if state: await state.clear()


async def _handle_registration_continuation(
    db_session: AsyncSession,
    state: FSMContext,
    bot: AiogramBot,
    message_or_callback_query: types.Message | types.CallbackQuery,
):
    current_fsm_data = await state.get_data()
    registrant_user_id = current_fsm_data.get("registrant_telegram_id")
    initiator_user_id = message_or_callback_query.from_user.id

    user_lang_code = current_fsm_data.get("selected_language", config.CFG_ADMIN_LANG)
    _user_translator = get_translator(user_lang_code)

    username_value = current_fsm_data["name"]
    password_value = current_fsm_data["password"]
    nickname_value = current_fsm_data.get("nickname", username_value)

    user_full_name = message_or_callback_query.from_user.full_name

    is_initiator_of_start_admin = current_fsm_data.get("is_admin_registrar", False)
    tt_account_type_chosen_by_admin = current_fsm_data.get("tt_account_type")

    source_info = {
        "type": "telegram",
        "telegram_id": registrant_user_id,
        "telegram_full_name": user_full_name,
        "selected_language": user_lang_code,
        "nickname": nickname_value,
        "is_admin_registrar": is_initiator_of_start_admin,
        "tt_account_type": tt_account_type_chosen_by_admin,
        "registrar_telegram_id": initiator_user_id,
    }

    if config.VERIFY_REGISTRATION and not is_initiator_of_start_admin:
        global request_id_counter
        request_id_counter += 1
        current_request_id = request_id_counter

        global registration_requests
        registration_requests[current_request_id] = {
            "registrant_user_id": registrant_user_id,
            "username_value": username_value,
            "password_value": password_value,
            "nickname_value": nickname_value,
            "source_info": source_info,
        }
        logger.info(f"Reg request {current_request_id} for TG user {registrant_user_id} ({username_value}) stored for admin verification.")

        admin_notify_lang = get_translator(get_admin_lang_code())
        admin_msg_text = admin_notify_lang('Registration request:') + "\n" + \
                         admin_notify_lang('Username:') + f" {username_value}\n"
        if nickname_value != username_value: admin_msg_text += admin_notify_lang('Nickname:') + f" {nickname_value}\n"
        admin_msg_text += admin_notify_lang('Telegram User:') + f" {user_full_name} (ID: {registrant_user_id})\n" + \
                          admin_notify_lang('Approve registration?')

        builder = InlineKeyboardBuilder()
        builder.button(text=admin_notify_lang("Yes"), callback_data=AdminVerificationCallback(action="verify", user_id=current_request_id))
        builder.button(text=admin_notify_lang("No"), callback_data=AdminVerificationCallback(action="reject", user_id=current_request_id))
        builder.adjust(2)

        for admin_id in config.ADMIN_IDS:
            try: await bot.send_message(admin_id, admin_msg_text, reply_markup=builder.as_markup())
            except Exception as e: logger.error(f"Error sending verification to admin {admin_id}: {e}", exc_info=True)

        reply_text = _user_translator("Registration request sent to administrators. Please wait for approval.")
        if isinstance(message_or_callback_query, types.Message): await message_or_callback_query.answer(reply_text)
        elif isinstance(message_or_callback_query, types.CallbackQuery): await message_or_callback_query.message.answer(reply_text)

        await state.set_state(RegistrationStates.waiting_admin_approval)
    else:
        if is_initiator_of_start_admin:
            logger.info(f"Admin {initiator_user_id} bypassing admin verification for user {username_value} (registrant_id: {registrant_user_id}).")

        await _process_actual_registration(
            db_session=db_session, registrant_user_id=registrant_user_id,
            username_val=username_value, password_val_reg=password_value, nickname_val=nickname_value,
            source_info=source_info, state=state, bot=bot
        )

logger.info("Registration logic helpers configured.")
