import logging

from aiogram import Bot as AiogramBot
from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db import is_telegram_id_registered
from ...core.localization import get_translator
from ...teamtalk import users as tt_users_service
from ..schemas import RegistrationStateData
from ..states import RegistrationStates
from .reg_callback_data import TTAccountTypeCallback
from .reg_logic_helpers import (
    _ask_nickname_preference,
    _handle_registration_continuation,
)

logger = logging.getLogger(__name__)

fsm_router = Router()


import pytalk  # New import


@fsm_router.message(RegistrationStates.awaiting_username)
async def username_handler(pytalk_bot_instance: pytalk.TeamTalkBot, message: types.Message, state: FSMContext):
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})

    user_lang_code = state_data.selected_language or settings.bot_admin_lang
    _ = get_translator(user_lang_code)

    username = message.text.strip()
    if not username:
        await message.reply(_("Hello! Please enter a username for registration."))
        return

    logger.debug("Validating username from Telegram: '%s' for user %s", username, message.from_user.id)
    username_check_result = await tt_users_service.check_username_exists(pytalk_bot_instance, username)

    if username_check_result is True:
        await message.reply(_("Sorry, this username is already taken. Please choose another username."))
    elif username_check_result is False:
        state_data.name = username
        await state.set_data(state_data.model_dump())
        await message.reply(_("Now enter a password."))
        await state.set_state(RegistrationStates.awaiting_password)
    else:
        logger.error("Username check error for user %s with username '%s'.", message.from_user.id, username)
        await message.reply(_("Registration error. Please try again later or contact an administrator."))


@fsm_router.message(RegistrationStates.awaiting_password)
async def password_handler(
    pytalk_bot_instance: pytalk.TeamTalkBot, # New argument
    message: types.Message, state: FSMContext, db_session: AsyncSession, bot: AiogramBot
):
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})

    user_lang_code = state_data.selected_language or settings.bot_admin_lang
    _ = get_translator(user_lang_code)

    if not state_data.is_admin_registrar and await is_telegram_id_registered(
        db_session, state_data.registrant_telegram_id
    ):
        await message.reply(
            _("This Telegram account has already registered a TeamTalk account. Only one registration is allowed.")
        )
        await state.clear()
        return

    state_data.password = message.text
    await state.set_data(state_data.model_dump())

    if state_data.is_admin_registrar:
        tt_admin_button_text = _("TeamTalk Admin")
        tt_user_button_text = _("TeamTalk User")
        builder = InlineKeyboardBuilder()
        builder.button(
            text=tt_admin_button_text,
            callback_data=TTAccountTypeCallback(action="select", account_type="admin"),
        )
        builder.button(
            text=tt_user_button_text,
            callback_data=TTAccountTypeCallback(action="select", account_type="user"),
        )
        builder.adjust(1)
        prompt_message_admin = _(
            "This TeamTalk account will be for username '{username}'.\nDo you want to register it as a TeamTalk 'Admin' or a regular 'User' on the server?"
        ).format(username=state_data.name)
        await message.reply(prompt_message_admin, reply_markup=builder.as_markup())
        await state.set_state(RegistrationStates.awaiting_tt_account_type)
    else:
        await _ask_nickname_preference(message, state, state_data.name, user_lang_code)


@fsm_router.message(RegistrationStates.awaiting_nickname)
async def nickname_input_handler(
    pytalk_bot_instance: pytalk.TeamTalkBot, # New argument
    message: types.Message, state: FSMContext, bot: AiogramBot, db_session: AsyncSession
):
    nickname_value = message.text.strip()
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})

    user_lang_code = state_data.selected_language or settings.bot_admin_lang
    _ = get_translator(user_lang_code)

    if not nickname_value:
        await message.reply(_("Nickname cannot be empty. Please enter a valid nickname."))
        return

    state_data.nickname = nickname_value
    await state.set_data(state_data.model_dump())

    await _handle_registration_continuation(
        db_session=db_session,
        state=state,
        bot=bot,
        message_or_callback_query=message,
    )


logger.info("Registration FSM message handlers configured.")
