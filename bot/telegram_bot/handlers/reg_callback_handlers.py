import logging

from aiogram import Bot as AiogramBot
from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db import (
    get_and_remove_pending_telegram_registration,
    is_telegram_id_registered,
)
from ...core.localization import get_admin_lang_code, get_translator
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
):
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
            _( "You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed."
            ),
        )
        await state.clear()
        return

    await bot.send_message(user.id, _("Hello! Please enter a username for registration."))
    await state.set_state(RegistrationStates.awaiting_username)


@callback_router.callback_query(
    RegistrationStates.awaiting_tt_account_type, TTAccountTypeCallback.filter(F.action == "select")
)
async def tt_account_type_choice_handler(
    callback_query: types.CallbackQuery, callback_data: TTAccountTypeCallback, state: FSMContext
):
    fsm_data = await state.get_data()
    state_data = RegistrationStateData.model_validate(fsm_data or {})

    user_lang_code = state_data.selected_language or settings.bot_admin_lang
    _ = get_translator(user_lang_code)

    state_data.tt_account_type = callback_data.account_type
    await state.set_data(state_data.model_dump())

    logger.info("Admin %s chose TeamTalk account type: %s for user %s", callback_query.from_user.id, callback_data.account_type, state_data.name)

    await callback_query.answer()

    await _ask_nickname_preference(
        callback_query, state, state_data.name, user_lang_code
    )


@callback_router.callback_query(AdminVerificationCallback.filter(F.action.in_({"verify", "reject"})))
async def admin_verification_handler(
    callback_query: types.CallbackQuery,
    callback_data: AdminVerificationCallback,
    bot: AiogramBot,
    db_session: AsyncSession,
):
    request_key_str = callback_data.request_key
    decision_action = callback_data.action

    admin_lang_code = get_admin_lang_code()
    _ = get_translator(admin_lang_code)

    pending_reg_data_model = await get_and_remove_pending_telegram_registration(
        db_session, request_key_str
    )

    if not pending_reg_data_model:
        await callback_query.answer(
            _("Registration request not found, outdated, or already processed."),
            show_alert=True,
        )
        try:
            await callback_query.message.delete()
        except Exception as e:
            logger.debug("Error deleting admin verification message: %s", e)
        return

    registrant_user_tg_id = pending_reg_data_model.registrant_telegram_id
    source_info_from_request = pending_reg_data_model.source_info
    registrant_tg_username = source_info_from_request.get("telegram_username")

    user_specific_lang_code = source_info_from_request.get(
        "selected_language", settings.bot_admin_lang
    )
    _ = get_translator(user_specific_lang_code)

    if decision_action == "verify" and await is_telegram_id_registered(
        db_session, registrant_user_tg_id
    ):
        await callback_query.answer(
            _("This Telegram account has already a TeamTalk account linked."), show_alert=True
        )
        try:
            await bot.send_message(
                registrant_user_tg_id,
                _( "Your registration request was processed, but this Telegram account already has a TeamTalk account linked. Only one registration is allowed."
                ),
            )
        except Exception as e:
            logger.warning(
                "Could not notify user %s about being already registered: %s", registrant_user_tg_id, e
            )
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        return

    # Construct the state_data model from the pending registration data
    state_data_from_pending = RegistrationStateData(
        registrant_telegram_id=registrant_user_tg_id,
        name=pending_reg_data_model.username,
        password=pending_reg_data_model.password_cleartext,
        nickname=pending_reg_data_model.nickname,
        selected_language=user_specific_lang_code,
        is_admin_registrar=source_info_from_request.get("is_admin_registrar", False),
        tt_account_type=source_info_from_request.get("tt_account_type"),
    )

    if decision_action == "verify":
        await callback_query.answer(
            _("User {username} registration approved.").format(username=state_data_from_pending.name),
            show_alert=True,
        )
        source_info_from_request["approved_by_admin_id"] = callback_query.from_user.id

        reg_success, __, __ = await _process_actual_registration(
            db_session=db_session,
            state_data=state_data_from_pending,
            source_info=source_info_from_request,
            state=None,  # No FSM state to clear here
            bot=bot,
        )

        if reg_success:
            try:
                await bot.send_message(
                    registrant_user_tg_id,
                    _("Your registration has been approved by the administrator. You can now use TeamTalk."),
                )
            except Exception as e:
                logger.warning("Could not send approval notification to user %s: %s", registrant_user_tg_id, e)

            acting_admin_id = callback_query.from_user.id
            acting_admin_name = callback_query.from_user.full_name

            registrant_telegram_info = (
                f"Registrant Telegram ID: {pending_reg_data_model.registrant_telegram_id}"
            )
            if registrant_tg_username:
                registrant_telegram_info += (
                    f"\nRegistrant Telegram Username: @{registrant_tg_username}"
                )

            notification_message = (
                f"ℹ️ Registration APPROVED by admin {acting_admin_name} (ID: {acting_admin_id}).\n\n"
                f"TeamTalk User: {state_data_from_pending.name}\n"
                f"{registrant_telegram_info}"
            )

            if settings.admin_ids:
                for other_admin_id in settings.admin_ids:
                    if other_admin_id != acting_admin_id:
                        logger.info(
                            "Notifying admin %s about registration approval by %s for TT user %s", other_admin_id, acting_admin_id, state_data_from_pending.name
                        )
                        await bot.send_message(
                            chat_id=other_admin_id, text=notification_message
                        )
            else:
                logger.info("No ADMIN_IDS configured, skipping notification to other admins.")
        else:
            logger.error(
                "Registration for TT user %s (TG ID: %s) was approved by admin %s, but _process_actual_registration failed.",
                state_data_from_pending.name, registrant_user_tg_id, callback_query.from_user.id
            )
            try:
                await bot.send_message(
                    callback_query.from_user.id,
                    _( "CRITICAL: Registration for {username} was approved, but the final registration step failed. Please check logs."
                    ).format(username=state_data_from_pending.name),
                )
            except Exception as e_admin_crit:
                logger.error("Failed to send critical failure notice to approving admin %s: %s", callback_query.from_user.id, e_admin_crit)

    elif decision_action == "reject":
        await callback_query.answer(
            _("User {username} registration declined.").format(username=state_data_from_pending.name),
            show_alert=True,
        )
        try:
            await bot.send_message(
                registrant_user_tg_id,
                _("Your registration has been declined by the administrator."),
            )
        except Exception as e:
            logger.warning(
                "Could not send decline notification to user %s: %s", registrant_user_tg_id, e
            )

        acting_admin_id = callback_query.from_user.id
        acting_admin_name = callback_query.from_user.full_name

        registrant_telegram_info = (
            f"Registrant Telegram ID: {pending_reg_data_model.registrant_telegram_id}"
        )
        if registrant_tg_username:
            registrant_telegram_info += (
                f"\nRegistrant Telegram Username: @{registrant_tg_username}"
            )

        notification_message = (
            f"ℹ️ Registration REJECTED by admin {acting_admin_name} (ID: {acting_admin_id}).\n\n"
            f"TeamTalk User: {state_data_from_pending.name}\n"
            f"{registrant_telegram_info}"
        )

        if settings.admin_ids:
            for other_admin_id in settings.admin_ids:
                if other_admin_id != acting_admin_id:
            logger.info("Notifying admin %s about registration rejection by %s for TT user %s", other_admin_id, acting_admin_id, state_data_from_pending.name)
                    await bot.send_message(chat_id=other_admin_id, text=notification_message)
        else:
            logger.info(
                "No ADMIN_IDS configured, skipping notification to other admins about rejection."
            )

    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.debug("Could not remove buttons from admin message: %s", e)


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
):
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
                "Username not found in state for nickname generation. User: %s", callback_query.from_user.id
            )
            await callback_query.message.answer(
                _("Error: Username not found. Please start over.")
            )
            await state.clear()
            return
        state_data.nickname = state_data.name
        await state.set_data(state_data.model_dump())
        await _handle_registration_continuation(
            db_session=db_session,
            state=state,
            bot=bot,
            message_or_callback_query=callback_query,
        )
    else:
        logger.warning("Invalid choice action '%s' in nickname_choice_handler by user %s", choice_action, callback_query.from_user.id)
        await callback_query.message.answer(_("Invalid choice. Please try again."))


logger.info("Registration callback handlers configured and updated to use reg_callback_data.")
