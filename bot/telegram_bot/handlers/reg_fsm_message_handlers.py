import logging
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Bot as AiogramBot, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ...core import config
from ...core.db import is_telegram_id_registered
from ...teamtalk import users as tt_users_service
from ...core.localization import get_translator
from ..states import RegistrationStates

from .reg_logic_helpers import _ask_nickname_preference, _handle_registration_continuation
from .reg_callback_data import TTAccountTypeCallback

logger = logging.getLogger(__name__)

fsm_router = Router()

@fsm_router.message(RegistrationStates.awaiting_username)
async def username_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_lang_code = data.get("selected_language", config.CFG_ADMIN_LANG)
    _ = get_translator(user_lang_code)

    username = message.text.strip()
    if not username:
        await message.reply(_("Hello! Please enter a username for registration."))
        return

    logger.debug(f"Validating username from Telegram: '{username}' for user {message.from_user.id}")
    username_check_result = await tt_users_service.check_username_exists(username)

    if username_check_result is True:
        await message.reply(_("Sorry, this username is already taken. Please choose another username."))
    elif username_check_result is False:
        await state.update_data(name=username)
        await message.reply(_("Now enter a password."))
        await state.set_state(RegistrationStates.awaiting_password)
    else:
        logger.error(f"Username check error for user {message.from_user.id} with username '{username}'.")
        await message.reply(_("Registration error. Please try again later or contact an administrator."))

@fsm_router.message(RegistrationStates.awaiting_password)
async def password_handler(message: types.Message, state: FSMContext, db_session: AsyncSession, bot: AiogramBot):
    initiator_telegram_id = message.from_user.id
    current_state_data = await state.get_data()
    user_lang_code = current_state_data.get("selected_language", config.CFG_ADMIN_LANG)
    _ = get_translator(user_lang_code)

    is_admin_registrar = current_state_data.get("is_admin_registrar", False)
    registrant_telegram_id = current_state_data.get("registrant_telegram_id", initiator_telegram_id)

    if not is_admin_registrar and await is_telegram_id_registered(db_session, registrant_telegram_id):
        await message.reply(_("This Telegram account has already registered a TeamTalk account. Only one registration is allowed."))
        await state.clear()
        return

    password_value = message.text
    await state.update_data(password=password_value)

    username_value = current_state_data["name"]

    if is_admin_registrar:
        tt_admin_button_text = _("TeamTalk Admin")
        tt_user_button_text = _("TeamTalk User")
        builder = InlineKeyboardBuilder()
        builder.button(text=tt_admin_button_text, callback_data=TTAccountTypeCallback(action="select", account_type="admin"))
        builder.button(text=tt_user_button_text, callback_data=TTAccountTypeCallback(action="select", account_type="user"))
        builder.adjust(1)
        prompt_message_admin = _("This TeamTalk account will be for username '{username}'.\nDo you want to register it as a TeamTalk 'Admin' or a regular 'User' on the server?").format(username=username_value)
        await message.reply(prompt_message_admin, reply_markup=builder.as_markup())
        await state.set_state(RegistrationStates.awaiting_tt_account_type)
    else:
        await _ask_nickname_preference(message, state, username_value, user_lang_code)


@fsm_router.message(RegistrationStates.awaiting_nickname)
async def nickname_input_handler(message: types.Message, state: FSMContext, bot: AiogramBot, db_session: AsyncSession):
    nickname_value = message.text.strip()
    current_state_data = await state.get_data()
    user_lang_code = current_state_data.get("selected_language", config.CFG_ADMIN_LANG)
    _ = get_translator(user_lang_code)

    if not nickname_value:
        await message.reply(_("Nickname cannot be empty. Please enter a valid nickname."))
        return

    await state.update_data(nickname=nickname_value)

    await _handle_registration_continuation(
        db_session=db_session,
        state=state,
        bot=bot,
        message_or_callback_query=message
    )

logger.info("Registration FSM message handlers configured.")
