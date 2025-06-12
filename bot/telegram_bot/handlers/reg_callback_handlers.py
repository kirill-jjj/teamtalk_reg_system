import logging
from typing import Any, Dict, Optional

from aiogram import Bot as AiogramBot
from aiogram import F, Router, types

# CallbackData itself is no longer defined here, but imported for type hinting if needed,
# or used by the imported CallbackData classes.
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import (
    InlineKeyboardBuilder,  # Not used directly in this file after refactor
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import config
from ...core.db import (
    get_and_remove_pending_telegram_registration,
    is_telegram_id_registered,
)
from ...core.localization import get_admin_lang_code, get_translator
from ..states import RegistrationStates
from .reg_callback_data import (
    AdminVerificationCallback,
    LanguageCallback,
    NicknameChoiceCallback,
    TTAccountTypeCallback,
)
from .reg_logic_helpers import (
    _ask_nickname_preference,
    _handle_registration_continuation,
    _process_actual_registration,
)

logger = logging.getLogger(__name__)

callback_router = Router()

# CallbackData class definitions were moved to reg_callback_data.py

# Handler functions - ensure their filters match the new prefixes in reg_callback_data.py
# LanguageCallback prefix is now "reg_lang"
# NicknameChoiceCallback prefix is now "reg_nick_choice"
# AdminVerificationCallback prefix is now "reg_admin_verify"
# TTAccountTypeCallback prefix is now "reg_tt_type"

@callback_router.callback_query(RegistrationStates.choosing_language, LanguageCallback.filter(F.action == "select")) # Assuming action was part of original logic implicitly or explicitly
async def language_selection_handler(callback_query: types.CallbackQuery, callback_data: LanguageCallback, state: FSMContext, bot: AiogramBot, db_session: AsyncSession):
    user = callback_query.from_user
    user_lang_code = callback_data.language_code # 'language_code' is from LanguageCallback definition
    await state.update_data(selected_language=user_lang_code, registrant_telegram_id=user.id)

    _ = get_translator(user_lang_code)
    await callback_query.answer(_("Language set successfully."))

    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.debug(f"Could not delete language selection message: {e}")

    data = await state.get_data()
    is_admin_registrar = data.get("is_admin_registrar", False)

    if not is_admin_registrar and await is_telegram_id_registered(db_session, user.id):
        await bot.send_message(user.id, _("You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed."))
        await state.clear()
        return

    await bot.send_message(user.id, _("Hello! Please enter a username for registration."))
    await state.set_state(RegistrationStates.awaiting_username)


@callback_router.callback_query(RegistrationStates.awaiting_tt_account_type, TTAccountTypeCallback.filter(F.action == "select")) # Assuming action
async def tt_account_type_choice_handler(callback_query: types.CallbackQuery, callback_data: TTAccountTypeCallback, state: FSMContext, bot: AiogramBot):
    current_fsm_data = await state.get_data()
    user_lang_code = current_fsm_data.get("selected_language", config.CFG_ADMIN_LANG)
    _ = get_translator(user_lang_code)

    await state.update_data(tt_account_type=callback_data.account_type) # 'account_type' from TTAccountTypeCallback
    logger.info(f"Admin {callback_query.from_user.id} chose TeamTalk account type: {callback_data.account_type} for user {current_fsm_data.get('name')}")

    await callback_query.answer()

    username_value = current_fsm_data.get("name", _("this account"))
    await _ask_nickname_preference(callback_query, state, username_value, user_lang_code)


# AdminVerificationCallback prefix is now "reg_admin_verify"
# The filter might need to be adjusted if action was part of it, e.g., AdminVerificationCallback.filter(F.action == "verify")
# Original was AdminVerificationCallback.filter() - assuming it implies matching any action defined in the callback.
# The callback data definition has 'action: str'. Let's assume specific actions like "verify" and "reject".
@callback_router.callback_query(AdminVerificationCallback.filter(F.action.in_({"verify", "reject"})))
async def admin_verification_handler(callback_query: types.CallbackQuery, callback_data: AdminVerificationCallback, bot: AiogramBot, db_session: AsyncSession):
    request_key_str = callback_data.request_key # Field name updated in AdminVerificationCallback
    decision_action = callback_data.action # This is "verify" or "reject"

    admin_id_str = str(callback_query.from_user.id)
    admin_lang_code = get_admin_lang_code()
    _ = get_translator(admin_lang_code)

    # Retrieve and remove the pending registration from the database
    pending_reg_data_model = await get_and_remove_pending_telegram_registration(db_session, request_key_str)

    if not pending_reg_data_model:
        await callback_query.answer(_("Registration request not found, outdated, or already processed."), show_alert=True)
        try: await callback_query.message.delete()
        except Exception as e: logger.debug(f"Error deleting admin verification message: {e}")
        return

    # Adapt to use attributes from the SQLAlchemy model instance
    registrant_user_tg_id = pending_reg_data_model.registrant_telegram_id
    username_val = pending_reg_data_model.username
    password_val_cb = pending_reg_data_model.password_cleartext
    nickname_val = pending_reg_data_model.nickname
    source_info_from_request = pending_reg_data_model.source_info # This is already a dict

    user_specific_lang_code = source_info_from_request.get("selected_language", config.CFG_ADMIN_LANG)
    _user_specific_translator = get_translator(user_specific_lang_code)

    # Check if already registered *before* processing, especially for "verify"
    if decision_action == "verify" and await is_telegram_id_registered(db_session, registrant_user_tg_id):
        await callback_query.answer(_("This Telegram account has already a TeamTalk account linked."), show_alert=True)
        try:
            await bot.send_message(registrant_user_tg_id, _user_specific_translator("Your registration request was processed, but this Telegram account already has a TeamTalk account linked. Only one registration is allowed."))
        except Exception as e: logger.warning(f"Could not notify user {registrant_user_tg_id} about being already registered: {e}")
        try: await callback_query.message.delete()
        except: pass
        return

    if decision_action == "verify":
        await callback_query.answer(_("User {} registration approved.").format(username_val), show_alert=True)
        source_info_from_request["approved_by_admin_id"] = callback_query.from_user.id
        await _process_actual_registration(
            db_session=db_session, registrant_user_id=registrant_user_tg_id,
            username_val=username_val, password_val_reg=password_val_cb, nickname_val=nickname_val,
            source_info=source_info_from_request, state=None, bot=bot
        )
        try:
            await bot.send_message(registrant_user_tg_id, _user_specific_translator("Your registration has been approved by the administrator. You can now use TeamTalk."))
        except Exception as e: logger.warning(f"Could not send approval notification to user {registrant_user_tg_id}: {e}")

    elif decision_action == "reject":
        await callback_query.answer(_("User {} registration declined.").format(username_val), show_alert=True)
        try:
            await bot.send_message(registrant_user_tg_id, _user_specific_translator("Your registration has been declined by the administrator."))
        except Exception as e: logger.warning(f"Could not send decline notification to user {registrant_user_tg_id}: {e}")

    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception as e: logger.debug(f"Could not remove buttons from admin message: {e}")

# NicknameChoiceCallback prefix is now "reg_nick_choice"
@callback_router.callback_query(RegistrationStates.awaiting_nickname_choice, NicknameChoiceCallback.filter(F.action.in_({"provide", "generate"})))
async def nickname_choice_handler(callback_query: types.CallbackQuery, callback_data: NicknameChoiceCallback, state: FSMContext, bot: AiogramBot, db_session: AsyncSession):
    choice_action = callback_data.action
    current_state_data = await state.get_data()
    user_lang_code = current_state_data.get("selected_language", config.CFG_ADMIN_LANG)
    _ = get_translator(user_lang_code)

    await callback_query.answer()
    try:
      await callback_query.message.delete()
    except Exception as e:
        logger.debug(f"Could not delete nickname choice message: {e}")

    if choice_action == "provide":
        await callback_query.message.answer(_("Please enter your desired nickname."))
        await state.set_state(RegistrationStates.awaiting_nickname)
    elif choice_action == "generate":
        username_value = current_state_data.get("name")
        if not username_value:
            logger.error(f"Username not found in state for nickname generation. User: {callback_query.from_user.id}")
            await callback_query.message.answer(_("Error: Username not found. Please start over."))
            await state.clear()
            return
        await state.update_data(nickname=username_value)
        await _handle_registration_continuation(
            db_session=db_session, state=state, bot=bot, message_or_callback_query=callback_query
        )
    else:
        logger.warning(f"Invalid choice action '{choice_action}' in nickname_choice_handler by user {callback_query.from_user.id}")
        await callback_query.message.answer(_("Invalid choice. Please try again."))

logger.info("Registration callback handlers configured and updated to use reg_callback_data.")
