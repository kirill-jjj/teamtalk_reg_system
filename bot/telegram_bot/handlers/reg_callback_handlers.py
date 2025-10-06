"""This module handles callbacks for the registration flow."""
import contextlib
import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router, types
from aiogram.fsm.context import FSMContext
from pydantic import parse_obj_as
import pytalk
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db import (
    get_and_remove_pending_telegram_registration,
    is_telegram_id_registered,
)
from ...core.db.models import PendingTelegramRegistration
from ...core.localization import get_translator
from ...utils.schemas import TelegramSourceInfo
from ..schemas import RegistrationStateData
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
    _notify_admins_about_decision,
    _process_actual_registration,
)

logger = logging.getLogger(__name__)

callback_router = Router()


@callback_router.callback_query(
    RegistrationStates.choosing_language, LanguageCallback.filter(F.action == "select")
)
async def language_selection_handler(
    callback_query: types.CallbackQuery,
    callback_data: LanguageCallback,
    state: FSMContext,
    bot: AiogramBot,
    db_session: AsyncSession,
) -> None:
    """Handles the language selection callback."""
    user = callback_query.from_user
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})

    state_data.selected_language = callback_data.language_code
    state_data.registrant_telegram_id = user.id
    await state.set_data(state_data.model_dump())

    _ = get_translator(state_data.selected_language)
    await callback_query.answer(_("Language set successfully."))

    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.debug("Could not delete language selection message: %s", e)

    if (
        not state_data.is_admin_registrar
        and not state_data.is_deeplink_registration
        and await is_telegram_id_registered(db_session, user.id)
    ):
        await bot.send_message(
            user.id,
            _(
                "You have already registered one TeamTalk account from this "
                "Telegram account. Only one registration is allowed."
            ),
        )
        await state.clear()
        return

    await bot.send_message(
        user.id, _("Hello! Please enter a username for registration.")
    )
    await state.set_state(RegistrationStates.awaiting_username)


@callback_router.callback_query(
    RegistrationStates.awaiting_tt_account_type,
    TTAccountTypeCallback.filter(F.action == "select"),
)
async def tt_account_type_choice_handler(
    callback_query: types.CallbackQuery,
    callback_data: TTAccountTypeCallback,
    state: FSMContext,
) -> None:
    """Handles the TeamTalk account type choice callback."""
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})

    user_lang_code = state_data.selected_language or settings.bot_admin_lang
    _ = get_translator(user_lang_code)

    state_data.tt_account_type = callback_data.account_type
    await state.set_data(state_data.model_dump())

    logger.info(
        "Admin %s chose TeamTalk account type: %s for user %s",
        callback_query.from_user.id,
        callback_data.account_type,
        state_data.name,
    )

    await callback_query.answer()

    await _ask_nickname_preference(
        callback_query, state, state_data.name, user_lang_code
    )


async def _handle_verification_approve(
    callback_query: types.CallbackQuery,
    bot: AiogramBot,
    db_session: AsyncSession,
    pending_reg_data_model: "PendingTelegramRegistration",
    state_data_from_pending: "RegistrationStateData",
    source_info_from_request: dict,
    pytalk_bot_instance: "pytalk.TeamTalkBot",
) -> None:
    user_lang_code = state_data_from_pending.selected_language or \
        settings.bot_admin_lang
    _ = get_translator(user_lang_code)

    await callback_query.answer(
        _("User {username} registration approved.").format(
            username=state_data_from_pending.name
        ),
        show_alert=True,
    )
    source_info_from_request["approved_by_admin_id"] = callback_query.from_user.id

    reg_success, __, __ = await _process_actual_registration(
        pytalk_bot_instance=pytalk_bot_instance,
        db_session=db_session,
        state_data=state_data_from_pending,
        source_info=source_info_from_request,
        state=None,  # No FSM state to clear here
        bot=bot,
    )

    if reg_success:
        try:
            await bot.send_message(
                pending_reg_data_model.registrant_telegram_id,
                _(
                    "Your registration has been approved by the administrator. "
                    "You can now use TeamTalk."
                ),
            )
        except Exception as e:
            logger.warning(
                "Could not send approval notification to user %s: %s",
                pending_reg_data_model.registrant_telegram_id,
                e,
            )

        await _notify_admins_about_decision(
            bot=bot,
            acting_admin_id=callback_query.from_user.id,
            acting_admin_name=callback_query.from_user.full_name,
            registrant_telegram_id=pending_reg_data_model.registrant_telegram_id,
            registrant_tg_username=source_info_from_request.get(
                "telegram_username"
            ),
            teamtalk_username=state_data_from_pending.name,
            decision="approved",
        )
    else:
        logger.error(
            "Registration for TT user %s (TG ID: %s) was approved by admin %s, "
            "but _process_actual_registration failed.",
            state_data_from_pending.name,
            pending_reg_data_model.registrant_telegram_id,
            callback_query.from_user.id,
        )
        try:
            await bot.send_message(
                callback_query.from_user.id,
                _(
                    "CRITICAL: Registration for {username} was approved, but the "
                    "final registration step failed. Please check logs."
                ).format(username=state_data_from_pending.name),
            )
        except Exception:
            logger.exception(
                "Failed to send critical failure notice to approving admin %s:",
                callback_query.from_user.id,
            )


async def _handle_verification_reject(
    callback_query: types.CallbackQuery,
    bot: AiogramBot,
    pending_reg_data_model: PendingTelegramRegistration,
    state_data_from_pending: RegistrationStateData,
    source_info_from_request: dict
) -> None:
    user_lang_code = state_data_from_pending.selected_language or \
        settings.bot_admin_lang
    _ = get_translator(user_lang_code)

    await callback_query.answer(
        _("User {username} registration declined.").format(
            username=state_data_from_pending.name
        ),
        show_alert=True,
    )
    try:
        await bot.send_message(
            pending_reg_data_model.registrant_telegram_id,
            _("Your registration has been declined by the administrator."),
        )
    except Exception as e:
        logger.warning(
            "Could not send decline notification to user %s: %s",
            pending_reg_data_model.registrant_telegram_id,
            e,
        )

    await _notify_admins_about_decision(
        bot=bot,
        acting_admin_id=callback_query.from_user.id,
        acting_admin_name=callback_query.from_user.full_name,
        registrant_telegram_id=pending_reg_data_model.registrant_telegram_id,
        registrant_tg_username=source_info_from_request.get(
            "telegram_username"
        ),
        teamtalk_username=state_data_from_pending.name,
        decision="rejected",
    )




@callback_router.callback_query(AdminVerificationCallback.filter())
async def admin_verification_handler(
    callback_query: types.CallbackQuery,
    callback_data: AdminVerificationCallback,
    bot: AiogramBot,
    db_session: AsyncSession,
    dispatcher: Dispatcher,
) -> None:
    """Handles an admin's decision on a registration request."""
    request_key = callback_data.request_key
    action = callback_data.action
    _ = get_translator(settings.bot_admin_lang)

    pending_reg_data_model = await get_and_remove_pending_telegram_registration(
        db_session, request_key
    )

    if not pending_reg_data_model:
        await callback_query.answer(
            _("Registration request not found, outdated, or already processed."),
            show_alert=True,
        )
        with contextlib.suppress(Exception):  # Ignore if message can't be edited
            await callback_query.message.edit_text(
                _("This registration request has already been handled.")
            )
        return

    source_info = parse_obj_as(TelegramSourceInfo, pending_reg_data_model.source_info)

    state_data_from_pending = RegistrationStateData(
        registrant_telegram_id=pending_reg_data_model.registrant_telegram_id,
        name=pending_reg_data_model.username,
        password=pending_reg_data_model.password_cleartext,
        nickname=pending_reg_data_model.nickname,
        selected_language=source_info.selected_language,
        is_admin_registrar=source_info.is_admin_registrar,
        tt_account_type=source_info.tt_account_type,
        is_deeplink_registration=source_info.is_deeplink_registration,
    )

    pytalk_bot_instance = dispatcher["pytalk_bot_instance"]

    if action == "verify":
        await _handle_verification_approve(
            callback_query,
            bot,
            db_session,
            pending_reg_data_model,
            state_data_from_pending,
            pending_reg_data_model.source_info,
            pytalk_bot_instance=pytalk_bot_instance,
        )
    elif action == "reject":
        await _handle_verification_reject(
            callback_query,
            bot,
            pending_reg_data_model,
            state_data_from_pending,
            pending_reg_data_model.source_info,
        )

    # Clean up the original verification message
    try:
        await callback_query.message.delete()
    except Exception:
        logger.debug("Could not delete admin verification message.")


@callback_router.callback_query(
    RegistrationStates.awaiting_nickname_choice,
    NicknameChoiceCallback.filter(F.action.in_({"provide", "generate"})),
)
async def nickname_choice_handler(
    callback_query: types.CallbackQuery,
    callback_data: NicknameChoiceCallback,
    state: FSMContext,
    bot: AiogramBot,
    db_session: AsyncSession,
    dispatcher: Dispatcher,
) -> None:
    """Handles the nickname choice callback."""
    choice_action = callback_data.action
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})

    user_lang_code = state_data.selected_language or settings.bot_admin_lang
    _ = get_translator(user_lang_code)

    await callback_query.answer()
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.debug("Could not delete nickname choice message: %s", e)

    if choice_action == "provide":
        await callback_query.message.answer(_("Please enter your desired nickname."))
        await state.set_state(RegistrationStates.awaiting_nickname)
    elif choice_action == "generate":
        if not state_data.name:
            logger.error(
                "Username not found in state for nickname generation. User: %s",
                callback_query.from_user.id,
            )
            await callback_query.message.answer(
                _("Error: Username not found. Please start over.")
            )
            await state.clear()
            return
        state_data.nickname = state_data.name
        await state.set_data(state_data.model_dump())

        # Retrieve pytalk_bot_instance from dispatcher's context
        pytalk_bot_instance = dispatcher["pytalk_bot_instance"]
        if not pytalk_bot_instance:
            logger.error(
                "pytalk_bot_instance not found in dispatcher context."
            )
            await callback_query.message.answer(
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
            message_or_callback_query=callback_query,
        )
    else:
        logger.warning(
            "Invalid choice action '%s' in nickname_choice_handler by user %s",
            choice_action,
            callback_query.from_user.id,
        )
        await callback_query.message.answer(_("Invalid choice. Please try again."))


logger.info(
    "Registration callback handlers configured and updated to use reg_callback_data."
)
