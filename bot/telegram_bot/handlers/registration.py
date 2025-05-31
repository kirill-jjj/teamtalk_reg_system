import logging
from typing import Dict, Optional

from aiogram import types, Bot as AiogramBot
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

from ...core import config, database, teamtalk_client as tt_client
# Измененный импорт локализации
from ...core.localization import get_translator, get_admin_lang_code 
from ..states import RegistrationStates
from ...utils.file_generator import generate_tt_file_content, generate_tt_link

logger = logging.getLogger(__name__)

registration_requests: Dict[int, Dict] = {}
request_id_counter = 0

async def start_command_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    telegram_id = message.from_user.id
    # Используем язык администратора для сообщения "уже зарегистрирован", т.к. язык пользователя еще не выбран
    _admin = get_translator(get_admin_lang_code())
    if await database.is_telegram_id_registered(telegram_id):
        await message.reply(_admin("You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed."))
        await state.clear()
        return

    # Используем английский по умолчанию для первого сообщения выбора языка
    _ = get_translator('en') 
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="English 🇬🇧", callback_data="set_lang_tg:en")],
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="set_lang_tg:ru")]
    ])
    await message.reply(_("Please choose your language:"), reply_markup=keyboard)
    await state.set_state(RegistrationStates.choosing_language)

async def language_selection_handler(callback_query: types.CallbackQuery, state: FSMContext, bot: AiogramBot):
    user_lang_code = callback_query.data.split(':')[1]
    await state.update_data(user_tg_lang=user_lang_code)

    _ = get_translator(user_lang_code)
    await callback_query.answer(_("Language set to English.")) 

    await bot.send_message(callback_query.from_user.id, _("Hello! Please enter a username for registration."))
    await state.set_state(RegistrationStates.awaiting_username)
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.debug(f"Could not delete language selection message: {e}")


async def username_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    data = await state.get_data()
    user_lang_code = data.get("user_tg_lang", 'en')
    _ = get_translator(user_lang_code)

    username = message.text.strip()
    if not username:
        await message.reply(_("Hello! Please enter a username for registration."))
        return

    logger.debug(f"Validating username from Telegram: '{username}' for user {message.from_user.id}")
    
    username_check_result = await tt_client.check_username_exists(username)

    if username_check_result is True:
        await message.reply(_("Sorry, this username is already taken. Please choose another username."))
        await state.set_state(RegistrationStates.awaiting_username)
    elif username_check_result is False:
        await state.update_data(name=username)
        await message.reply(_("Now enter a password."))
        await state.set_state(RegistrationStates.awaiting_password)
    else: 
        logger.error(f"Failed to check username existence for '{username}' due to an internal error.")
        await message.reply(_("Registration error. Please try again later or contact an administrator.") + " (Error checking username availability)")
        await state.set_state(RegistrationStates.awaiting_username)


async def password_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    user_tg_id = message.from_user.id
    data = await state.get_data()
    user_lang_code = data.get("user_tg_lang", 'en')
    _ = get_translator(user_lang_code)

    if await database.is_telegram_id_registered(user_tg_id):
        await message.reply(_("You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed."))
        await state.clear()
        return

    password_value = message.text
    await state.update_data(password=password_value, user_tg_id=user_tg_id)
    
    current_data = await state.get_data()
    username_value = current_data["name"]

    if config.VERIFY_REGISTRATION:
        global request_id_counter
        request_id_counter += 1
        request_id = request_id_counter
        
        registration_requests[request_id] = {
            "name": username_value,
            "password": password_value,
            "user_tg_id": user_tg_id,
            "user_tg_lang": user_lang_code,
            "telegram_full_name": message.from_user.full_name
        }
        logger.info(f"Storing registration request ID {request_id} for user {user_tg_id} ({username_value})")

        _admin = get_translator(get_admin_lang_code())
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_admin("Yes"), callback_data=f"verify_reg:yes:{request_id}"),
             InlineKeyboardButton(text=_admin("No"), callback_data=f"verify_reg:no:{request_id}")]
        ])
        
        admin_message_text = (
            f"{_admin('Registration request:')}\n"
            f"Username: {username_value}\n"
            f"Telegram User: {message.from_user.full_name} (ID: {user_tg_id})\n"
            f"{_admin('Approve registration?')}"
        )

        for admin_id_val in config.ADMIN_IDS:
            try:
                await bot.send_message(admin_id_val, admin_message_text, reply_markup=keyboard)
            except Exception as e:
                logger.error(f"Error sending verification request to admin {admin_id_val}: {e}")

        await message.reply(_("Registration request sent to administrators. Please wait for approval."))
        await state.set_state(RegistrationStates.waiting_admin_approval)
    else:
        source_info = {
            "type": "telegram",
            "telegram_id": user_tg_id,
            "telegram_full_name": message.from_user.full_name,
            "user_lang": user_lang_code
        }
        await _process_actual_registration(user_tg_id, username_value, password_value, source_info, state, bot)


async def admin_verification_handler(callback_query: types.CallbackQuery, state: FSMContext, bot: AiogramBot):
    action_type, decision, request_id_str = callback_query.data.split(':')
    request_id = int(request_id_str)

    _admin = get_translator(get_admin_lang_code()) 

    pending_reg_data = registration_requests.pop(request_id, None)

    if not pending_reg_data:
        await callback_query.answer(_admin("Registration request not found or outdated."), show_alert=True)
        try: await callback_query.message.delete()
        except: pass
        return

    username_val = pending_reg_data["name"]
    password_val_cb = pending_reg_data["password"]
    user_tg_id_val = pending_reg_data["user_tg_id"]
    user_tg_lang_val = pending_reg_data.get("user_tg_lang", 'en')
    user_telegram_full_name = pending_reg_data.get("telegram_full_name", "N/A")

    _user = get_translator(user_tg_lang_val) 

    if await database.is_telegram_id_registered(user_tg_id_val):
        await callback_query.answer(_admin("This Telegram account has already registered a TeamTalk account."), show_alert=True)
        try: 
            await bot.send_message(user_tg_id_val, _user("You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed."))
        except Exception as e:
            logger.warning(f"Could not notify user {user_tg_id_val} about being already registered: {e}")
        try: await callback_query.message.delete()
        except: pass
        return

    if decision == "yes":
        # Строка "User {} registration approved." будет переведена _admin() если она есть в .po
        await callback_query.answer(_admin("User {} registration approved.").format(username_val), show_alert=True)
        source_info = {
            "type": "telegram",
            "telegram_id": user_tg_id_val,
            "telegram_full_name": user_telegram_full_name, 
            "user_lang": user_tg_lang_val,
            "approved_by_admin": callback_query.from_user.id 
        }
        await _process_actual_registration(user_tg_id_val, username_val, password_val_cb, source_info, None, bot)
        
        try:
            await bot.send_message(user_tg_id_val, _user("Your registration has been approved by the administrator. You can now use TeamTalk."))
        except Exception as e:
            logger.warning(f"Could not send approval notification to user {user_tg_id_val}: {e}")
            
    elif decision == "no":
        # Строка "User {} registration declined." будет переведена _admin()
        await callback_query.answer(_admin("User {} registration declined.").format(username_val), show_alert=True)
        try:
            await bot.send_message(user_tg_id_val, _user("Your registration has been declined by the administrator."))
        except Exception as e:
            logger.warning(f"Could not send decline notification to user {user_tg_id_val}: {e}")

    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.debug(f"Could not remove buttons from admin message: {e}")

async def _process_actual_registration(
    user_id_val: int,
    username_val: str,
    password_val_reg: str,
    source_info: Dict,
    state: Optional[FSMContext], 
    bot: AiogramBot
):
    user_lang_code = source_info.get("user_lang", 'en')
    _ = get_translator(user_lang_code)

    success, reg_msg_key_or_detail, tt_file_content_val, tt_link_val = \
        await tt_client.perform_teamtalk_registration(username_val, password_val_reg, source_info, bot)

    if success:
        db_add_success = await database.add_telegram_registration(user_id_val, username_val)
        if not db_add_success:
            logger.error(f"CRITICAL: Failed to add Telegram ID {user_id_val} to database for TT user {username_val} after successful TT registration.")
            await bot.send_message(user_id_val, _("Registration error. Please try again later or contact an administrator.") + " (DB_SYNC_ERROR)")
            admin_notification = f"CRITICAL DB SYNC ERROR: User {username_val} (TG ID: {user_id_val}) registered on TeamTalk BUT FAILED to save to local database. Manual intervention may be required."
            for admin_tg_id in config.ADMIN_IDS:
                try: await bot.send_message(admin_tg_id, admin_notification)
                except: pass

        # Строка "User {} successfully registered." будет переведена функцией _()
        await bot.send_message(user_id_val, _("User {} successfully registered.").format(username_val))

        if tt_file_content_val and tt_link_val:
            tt_file_bytes = bytes(tt_file_content_val, encoding='utf-8')
            safe_server_name_for_file = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in config.SERVER_NAME).rstrip()
            if not safe_server_name_for_file: safe_server_name_for_file = "TeamTalk_Server"
            generated_filename = f"{safe_server_name_for_file}.tt"
            tt_buffered_file = BufferedInputFile(tt_file_bytes, filename=generated_filename)

            try:
                await bot.send_document(user_id_val, document=tt_buffered_file, caption=_("Your .tt file for quick connection"))
                link_text_part = _('Or use this TT link:\n')
                message_content = f"{link_text_part}`{tt_link_val}`"
                await bot.send_message(user_id_val, message_content, parse_mode="Markdown")
            except Exception as e_send:
                logger.error(f"Error sending .tt file or link to user {user_id_val}: {e_send}")
                await bot.send_message(user_id_val, "Could not send the .tt file or link. Please contact an admin.") # Эту строку тоже можно вынести в .po
    else:
        user_facing_error_message = _("Registration error. Please try again later or contact an administrator.")
        if reg_msg_key_or_detail and reg_msg_key_or_detail.startswith("UNEXPECTED_ERROR:"):
            logger.error(f"TT Registration unexpected error for {username_val}: {reg_msg_key_or_detail}")
        elif reg_msg_key_or_detail == "REG_FAILED_SDK_CLIENT":
             logger.error(f"TT Registration client-side SDK error for {username_val}")
        elif reg_msg_key_or_detail == "MODULE_UNAVAILABLE":
             logger.error(f"TT Registration failed for {username_val} because TT module/SDK was unavailable.")
        await bot.send_message(user_id_val, user_facing_error_message)

    if state:
        await state.clear()