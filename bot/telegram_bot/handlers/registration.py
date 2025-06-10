import logging
from typing import Dict, Optional

from aiogram import Bot as AiogramBot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from ...core import config, database
from ...core import teamtalk_client as tt_client
from ...core.config import FORCE_USER_LANG
from ...core.localization import (
    get_admin_lang_code,
    get_available_languages_for_display,
    get_translator,
)
from ...utils.file_generator import generate_tt_file_content, generate_tt_link
from ..states import RegistrationStates

logger = logging.getLogger(__name__)

router = Router()

registration_requests: Dict[int, Dict] = {}
request_id_counter = 0


@router.message(Command("start"))
async def start_command_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    telegram_id = message.from_user.id
    _ = get_translator(get_admin_lang_code())
    if await database.is_telegram_id_registered(telegram_id):
        await message.reply(
            _("You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed.")
        )
        await state.clear()
        return

    if FORCE_USER_LANG and FORCE_USER_LANG.strip():
        forced_lang_code = FORCE_USER_LANG.strip()
        _ = get_translator(forced_lang_code)
        original_string = "Hello! Please enter a username for registration."
        translated_string = _(original_string)

        if translated_string != original_string:
            logger.info(f"Forcing language to '{forced_lang_code}' for user {telegram_id} based on config.")
            await state.update_data(user_tg_lang=forced_lang_code)
            await message.reply(_(original_string))
            await state.set_state(RegistrationStates.awaiting_username)
            return
        else:
            logger.warning(
                f"FORCE_USER_LANG was set to '{forced_lang_code}', but this language pack seems unavailable or incomplete. Proceeding with language selection."
            )

    _ = get_translator("en")
    available_langs = get_available_languages_for_display()
    inline_keyboard_buttons = []
    if available_langs:
        for lang_info in available_langs:
            button_text = lang_info["native_name"] if lang_info["native_name"] else lang_info["code"].upper()
            inline_keyboard_buttons.append(
                [InlineKeyboardButton(text=button_text, callback_data="set_lang_tg:{}".format(lang_info['code']))]
            )

    if not inline_keyboard_buttons:
        logger.error("No languages discovered for Telegram language selection.")
        inline_keyboard_buttons.append([InlineKeyboardButton(text="English", callback_data="set_lang_tg:en")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard_buttons)
    await message.reply(_("Please choose your language:"), reply_markup=keyboard)
    await state.set_state(RegistrationStates.choosing_language)


@router.callback_query(RegistrationStates.choosing_language, F.data.startswith("set_lang_tg:"))
async def language_selection_handler(callback_query: types.CallbackQuery, state: FSMContext, bot: AiogramBot):
    user_lang_code = callback_query.data.split(":")[1]
    await state.update_data(user_tg_lang=user_lang_code)

    _ = get_translator(user_lang_code)
    await callback_query.answer(_("Language set successfully."))

    await bot.send_message(callback_query.from_user.id, _("Hello! Please enter a username for registration."))
    await state.set_state(RegistrationStates.awaiting_username)
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.debug(f"Could not delete language selection message: {e}")


@router.message(RegistrationStates.awaiting_username)
async def username_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    data = await state.get_data()
    user_lang_code = data.get("user_tg_lang", "en")
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
        logger.error(f"Registration error for user {message.from_user.id}: Error checking username availability for '{username}'.")
        await message.reply(_("Registration error. Please try again later or contact an administrator."))
        await state.set_state(RegistrationStates.awaiting_username)


@router.message(RegistrationStates.awaiting_password)
async def password_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    user_tg_id = message.from_user.id
    data = await state.get_data()
    user_lang_code = data.get("user_tg_lang", "en")
    _ = get_translator(user_lang_code)

    if await database.is_telegram_id_registered(user_tg_id):
        await message.reply(
            _("You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed.")
        )
        await state.clear()
        return

    password_value = message.text
    await state.update_data(password=password_value, user_tg_id=user_tg_id)

    current_data = await state.get_data()
    username_value = current_data["name"]

    yes_button_text = _("Yes")
    no_button_text = _("No (use username)")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=yes_button_text, callback_data="set_nickname_choice:yes")],
            [InlineKeyboardButton(text=no_button_text, callback_data="set_nickname_choice:no")],
        ]
    )

    prompt_message = _(
        "Your username will be '{username}'. Would you like to set a different nickname? If not, your nickname will be the same as your username."
    ).format(username=username_value)

    await message.reply(prompt_message, reply_markup=keyboard)
    await state.set_state(RegistrationStates.awaiting_nickname_choice)


@router.callback_query(F.data.startswith("verify_reg:"))
async def admin_verification_handler(callback_query: types.CallbackQuery, state: FSMContext, bot: AiogramBot):
    action_type, decision, request_id_str = callback_query.data.split(":")
    request_id = int(request_id_str)

    _ = get_translator(get_admin_lang_code())

    pending_reg_data = registration_requests.pop(request_id, None)

    if not pending_reg_data:
        await callback_query.answer(_("Registration request not found or outdated."), show_alert=True)
        try:
            await callback_query.message.delete()
        except:
            pass
        return

    username_val = pending_reg_data["name"]
    password_val_cb = pending_reg_data["password"]
    user_tg_id_val = pending_reg_data["user_tg_id"]
    user_tg_lang_val = pending_reg_data.get("user_tg_lang", "en")
    user_telegram_full_name = pending_reg_data.get("telegram_full_name", "N/A")
    nickname_val = pending_reg_data.get("nickname", username_val)

    if await database.is_telegram_id_registered(user_tg_id_val):
        await callback_query.answer(_("This Telegram account has already registered a TeamTalk account."), show_alert=True)

        _ = get_translator(user_tg_lang_val)
        try:
            await bot.send_message(
                user_tg_id_val,
                _("You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed."),
            )
        except Exception as e:
            logger.warning(f"Could not notify user {user_tg_id_val} about being already registered: {e}", exc_info=True)
        try:
            await callback_query.message.delete()
        except:
            pass
        return

    if decision == "yes":
        _ = get_translator(get_admin_lang_code())
        await callback_query.answer(_("User {} registration approved.").format(username_val), show_alert=True)

        source_info = {
            "type": "telegram",
            "telegram_id": user_tg_id_val,
            "telegram_full_name": user_telegram_full_name,
            "user_lang": user_tg_lang_val,
            "approved_by_admin": callback_query.from_user.id,
            "nickname": nickname_val,
        }
        await _process_actual_registration(user_tg_id_val, username_val, password_val_cb, nickname_val, source_info, None, bot)

        _ = get_translator(user_tg_lang_val)
        try:
            await bot.send_message(
                user_tg_id_val, _("Your registration has been approved by the administrator. You can now use TeamTalk.")
            )
        except Exception as e:
            logger.warning(f"Could not send approval notification to user {user_tg_id_val}: {e}", exc_info=True)

    elif decision == "no":
        _ = get_translator(get_admin_lang_code())
        await callback_query.answer(_("User {} registration declined.").format(username_val), show_alert=True)

        _ = get_translator(user_tg_lang_val)
        try:
            await bot.send_message(user_tg_id_val, _("Your registration has been declined by the administrator."))
        except Exception as e:
            logger.warning(f"Could not send decline notification to user {user_tg_id_val}: {e}", exc_info=True)

    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.debug(f"Could not remove buttons from admin message: {e}")


async def _process_actual_registration(
    user_id_val: int,
    username_val: str,
    password_val_reg: str,
    nickname_val: str,
    source_info: Dict,
    state: Optional[FSMContext],
    bot: AiogramBot,
):
    user_lang_code = source_info.get("user_lang", "en")
    _ = get_translator(user_lang_code)

    if "nickname" not in source_info:
        source_info["nickname"] = nickname_val

    success, reg_msg_key_or_detail, tt_file_content_val, tt_link_val = await tt_client.perform_teamtalk_registration(
        username_val, password_val_reg, nickname_val, source_info, bot
    )

    if success:
        db_add_success = await database.add_telegram_registration(user_id_val, username_val)
        if not db_add_success:
            logger.error(
                f"CRITICAL: Failed to add Telegram ID {user_id_val} to database for TT user {username_val} after successful TT registration."
            )
            await bot.send_message(user_id_val, _("Registration error. Please try again later or contact an administrator."))
            admin_notification = "CRITICAL DB SYNC ERROR: User {} (TG ID: {}) registered on TeamTalk BUT FAILED to save to local database. Manual intervention may be required.".format(username_val, user_id_val)
            for admin_tg_id in config.ADMIN_IDS:
                try:
                    await bot.send_message(admin_tg_id, admin_notification)
                except:
                    pass

        await bot.send_message(user_id_val, _("User {} successfully registered.").format(username_val))

        if tt_file_content_val and tt_link_val:
            tt_file_bytes = bytes(tt_file_content_val, encoding="utf-8")
            safe_server_name_for_file = "".join(
                c if c.isalnum() or c in (" ", "_", "-") else "_" for c in config.SERVER_NAME
            ).rstrip()
            if not safe_server_name_for_file:
                safe_server_name_for_file = "TeamTalk_Server"
            generated_filename = "{}.tt".format(safe_server_name_for_file)
            tt_buffered_file = BufferedInputFile(tt_file_bytes, filename=generated_filename)

            try:
                await bot.send_document(user_id_val, document=tt_buffered_file, caption=_("Your .tt file for quick connection"))
                link_text_part = _("Or use this TT link:\n")
                message_content = "{}`{}`".format(link_text_part, tt_link_val)
                await bot.send_message(user_id_val, message_content, parse_mode="Markdown")
            except Exception as e_send:
                logger.error(f"Error sending .tt file or link to user {user_id_val}: {e_send}", exc_info=True)
                await bot.send_message(user_id_val, "Could not send the .tt file or link. Please contact an admin.")
    else:
        user_facing_error_message = _("Registration error. Please try again later or contact an administrator.")
        if reg_msg_key_or_detail and reg_msg_key_or_detail.startswith("UNEXPECTED_ERROR:"):
            logger.error(f"TT Registration unexpected error for {username_val}: {reg_msg_key_or_detail}", exc_info=True)
        elif reg_msg_key_or_detail == "REG_FAILED_SDK_CLIENT":
            logger.error(f"TT Registration client-side SDK error for {username_val}")
        elif reg_msg_key_or_detail == "MODULE_UNAVAILABLE":
            logger.error(f"TT Registration failed for {username_val} because TT module/SDK was unavailable.")
        await bot.send_message(user_id_val, user_facing_error_message)

    if state:
        await state.clear()


async def _handle_registration_continuation(
    user_tg_id: int,
    username_value: str,
    password_value: str,
    nickname_value: str,
    user_lang_code: str,
    user_full_name: str,
    state: FSMContext,
    bot: AiogramBot,
    message_or_callback_query: types.Message | types.CallbackQuery,
):
    _user_translator = get_translator(user_lang_code)

    if config.VERIFY_REGISTRATION:
        global request_id_counter
        request_id_counter += 1
        request_id = request_id_counter

        registration_requests[request_id] = {
            "name": username_value,
            "password": password_value,
            "nickname": nickname_value,
            "user_tg_id": user_tg_id,
            "user_tg_lang": user_lang_code,
            "telegram_full_name": user_full_name,
        }
        logger.info(f"Storing registration request ID {request_id} for user {user_tg_id} ({username_value}, Nick: {nickname_value})")

        _ = get_translator(get_admin_lang_code())

        admin_message_text = "{}\n{}: {}\n".format(
            _('Registration request:'),
            _('Username:'),
            username_value
        )
        if nickname_value != username_value:
            admin_message_text += "{}: {}\n".format(_('Nickname:'), nickname_value)

        admin_message_text += "{}: {} (ID: {})\n{}".format(
            _('Telegram User:'),
            user_full_name,
            user_tg_id,
            _('Approve registration?')
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=_("Yes"), callback_data="verify_reg:yes:{}".format(request_id)),
                    InlineKeyboardButton(text=_("No"), callback_data="verify_reg:no:{}".format(request_id)),
                ]
            ]
        )

        for admin_id_val in config.ADMIN_IDS:
            try:
                await bot.send_message(admin_id_val, admin_message_text, reply_markup=keyboard)
            except Exception as e:
                logger.error(f"Error sending verification request to admin {admin_id_val}: {e}", exc_info=True)

        _ = _user_translator
        reply_text = _("Registration request sent to administrators. Please wait for approval.")
        if isinstance(message_or_callback_query, types.Message):
            await message_or_callback_query.answer(reply_text)
        elif isinstance(message_or_callback_query, types.CallbackQuery):
            await message_or_callback_query.message.answer(reply_text)

        await state.set_state(RegistrationStates.waiting_admin_approval)
    else:
        source_info = {
            "type": "telegram",
            "telegram_id": user_tg_id,
            "telegram_full_name": user_full_name,
            "user_lang": user_lang_code,
            "nickname": nickname_value,
        }
        await _process_actual_registration(user_tg_id, username_value, password_value, nickname_value, source_info, state, bot)


@router.callback_query(RegistrationStates.awaiting_nickname_choice, F.data.startswith("set_nickname_choice:"))
async def nickname_choice_handler(callback_query: types.CallbackQuery, state: FSMContext, bot: AiogramBot):
    choice = callback_query.data.split(":")[1]
    data = await state.get_data()
    user_lang_code = data.get("user_tg_lang", "en")
    _ = get_translator(user_lang_code)

    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.debug(f"Could not delete nickname choice message: {e}")

    if choice == "yes":
        await callback_query.message.answer(_("Please enter your desired nickname."))
        await state.set_state(RegistrationStates.awaiting_nickname)
    elif choice == "no":
        username_value = data["name"]
        password_value = data["password"]
        user_tg_id = data["user_tg_id"]
        await state.update_data(nickname=username_value)

        await _handle_registration_continuation(
            user_tg_id=user_tg_id,
            username_value=username_value,
            password_value=password_value,
            nickname_value=username_value,
            user_lang_code=user_lang_code,
            user_full_name=callback_query.from_user.full_name,
            state=state,
            bot=bot,
            message_or_callback_query=callback_query,
        )
    await callback_query.answer()


@router.message(RegistrationStates.awaiting_nickname)
async def nickname_input_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    nickname_value = message.text.strip()
    data = await state.get_data()
    user_lang_code = data.get("user_tg_lang", "en")
    _ = get_translator(user_lang_code)

    if not nickname_value:
        await message.reply(_("Nickname cannot be empty. Please enter a valid nickname."))
        return

    await state.update_data(nickname=nickname_value)

    username_value = data["name"]
    password_value = data["password"]
    user_tg_id = data["user_tg_id"]

    await _handle_registration_continuation(
        user_tg_id=user_tg_id,
        username_value=username_value,
        password_value=password_value,
        nickname_value=nickname_value,
        user_lang_code=user_lang_code,
        user_full_name=message.from_user.full_name,
        state=state,
        bot=bot,
        message_or_callback_query=message,
    )