"""This module handles FSM messages for the registration flow."""
import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
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


@fsm_router.message(RegistrationStates.awaiting_username, F.text)
async def awaiting_username_handler(
    message: types.Message, state: FSMContext, dispatcher: Dispatcher
) -> None:
    """Handles the username input from the user."""
    user_input = message.text.strip()
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})
    _ = get_translator(state_data.selected_language or settings.bot_admin_lang)

    if not user_input:
        await message.reply(
            _("Username cannot be empty. Please enter a valid username.")
        )
        return

    # Retrieve pytalk_bot_instance from dispatcher's context
    pytalk_bot_instance = dispatcher["pytalk_bot_instance"]
    if not pytalk_bot_instance:
        logger.error("pytalk_bot_instance not found in dispatcher context.")
        await message.reply(
            _(
                "Internal error: TeamTalk bot instance not available. "
                "Please contact an administrator."
            )
        )
        await state.clear()
        return

    try:
        username_exists = await tt_users_service.check_username_exists(
            pytalk_bot_instance, username=user_input
        )
        if username_exists is True:
            await message.reply(
                _("Sorry, this username is already taken. Please choose another one.")
            )
            return
        if username_exists is None:
            logger.error(
                "check_username_exists returned None (error) for username %s.",
                user_input,
            )
            await message.reply(
                _(
                    "An error occurred while checking the username. "
                    "Please try again later."
                )
            )
            return
    except Exception:
        logger.exception("Error checking username existence for %s:", user_input)
        await message.reply(
            _(
                "An error occurred while checking the username. "
                "Please try again later."
            )
        )
        return

    state_data.name = user_input
    await state.set_data(state_data.model_dump())

    await message.reply(_("Now enter a password."))
    await state.set_state(RegistrationStates.awaiting_password)


@fsm_router.message(RegistrationStates.awaiting_password, F.text)
async def awaiting_password_handler(message: types.Message, state: FSMContext) -> None:
    """Handles the password input from the user."""
    user_input = message.text.strip()
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})
    _ = get_translator(state_data.selected_language or settings.bot_admin_lang)

    if not user_input:
        await message.reply(
            _("Password cannot be empty. Please enter a valid password.")
        )
        return

    state_data.password = user_input
    await state.set_data(state_data.model_dump())

    await _ask_nickname_preference(
        message, state, state_data.name, state_data.selected_language
    )


@fsm_router.message(RegistrationStates.awaiting_nickname, F.text)
async def awaiting_nickname_handler(
    message: types.Message,
    state: FSMContext,
    db_session: AsyncSession,
    bot: AiogramBot,
    dispatcher: Dispatcher,
) -> None:
    """Handles the nickname input from the user."""
    user_input = message.text.strip()
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})
    _ = get_translator(state_data.selected_language or settings.bot_admin_lang)

    if not user_input:
        await message.reply(
            _("Nickname cannot be empty. Please enter a valid nickname.")
        )
        return

    state_data.nickname = user_input
    await state.set_data(state_data.model_dump())

    if state_data.is_admin_registrar:
        # If admin is registering, ask for account type (admin/user)
        builder = InlineKeyboardBuilder()
        builder.button(
            text=_("TeamTalk Admin"),
            callback_data=TTAccountTypeCallback(action="select", account_type="admin"),
        )
        builder.button(
            text=_("TeamTalk User"),
            callback_data=TTAccountTypeCallback(action="select", account_type="user"),
        )
        builder.adjust(1)
        await message.reply(
            _(
                "This TeamTalk account will be for username '{username}'.\n"
                "Do you want to register it as a TeamTalk 'Admin' or a regular 'User' "
                "on the server?"
            ).format(username=state_data.name),
            reply_markup=builder.as_markup(),
        )
        await state.set_state(RegistrationStates.awaiting_tt_account_type)
    else:
        # For regular users, proceed with registration
        pytalk_bot_instance = dispatcher["pytalk_bot_instance"]
        if not pytalk_bot_instance:
            logger.error("pytalk_bot_instance not found in dispatcher context.")
            await message.answer(
                _(
                    "Internal error: TeamTalk bot instance not available. "
                    "Please contact an administrator."
                )
            )
            await state.clear()
            return

        await _handle_registration_continuation(
            pytalk_bot_instance=pytalk_bot_instance,
            db_session=db_session,
            state=state,
            bot=bot,
            message_or_callback_query=message
        )
