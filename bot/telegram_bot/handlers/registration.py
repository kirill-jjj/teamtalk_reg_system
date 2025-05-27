import logging
from typing import Dict, Optional

from aiogram import types, Bot as AiogramBot
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

from ...core import config, database, teamtalk_client as tt_client
from ...core.localization import get_tg_strings, get_admin_lang_code
from ..states import RegistrationStates
from ...utils.file_generator import generate_tt_file_content, generate_tt_link # Re-import for clarity

logger = logging.getLogger(__name__)

# In-memory store for registration requests pending admin approval
# Key: request_id (int), Value: Dict containing user data like name, password, user_tg_id, user_tg_lang
registration_requests: Dict[int, Dict] = {}
request_id_counter = 0 # Simple counter for request IDs

async def start_command_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    telegram_id = message.from_user.id
    if await database.is_telegram_id_registered(telegram_id):
        # User's preferred language might not be set yet if they are already registered and type /start again
        # We could try to fetch it or default to bot's admin lang for this message
        # For simplicity, using admin lang for this specific "already registered" message.
        s = get_tg_strings(get_admin_lang_code())
        await message.reply(s["already_registered_tg"])
        await state.clear()
        return

    s = get_tg_strings() # Defaults to English for initial prompt
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="English 🇬🇧", callback_data="set_lang_tg:en")],
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="set_lang_tg:ru")]
    ])
    await message.reply(s["start_choose_lang"], reply_markup=keyboard)
    await state.set_state(RegistrationStates.choosing_language)

async def language_selection_handler(callback_query: types.CallbackQuery, state: FSMContext, bot: AiogramBot):
    user_lang_code = callback_query.data.split(':')[1]
    await state.update_data(user_tg_lang=user_lang_code)

    s = get_tg_strings(user_lang_code)
    await callback_query.answer(s["lang_set_to"]) # Show popup notification

    await bot.send_message(callback_query.from_user.id, s["prompt_username"])
    await state.set_state(RegistrationStates.awaiting_username)
    try:
        await callback_query.message.delete() # Clean up the language selection message
    except Exception as e:
        logger.debug(f"Could not delete language selection message: {e}")


async def username_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    data = await state.get_data()
    user_lang_code = data.get("user_tg_lang", 'en') # Default to 'en' if not set
    s = get_tg_strings(user_lang_code)

    username = message.text.strip()
    if not username:
        await message.reply(s["prompt_username"]) # Should not happen if Aiogram handles empty messages correctly
        return

    logger.debug(f"Validating username from Telegram: '{username}' for user {message.from_user.id}")

    if await tt_client.check_username_exists(username):
        await message.reply(s["username_taken"])
        # Stay in the same state to allow user to try another username
        await state.set_state(RegistrationStates.awaiting_username)
    else:
        await state.update_data(name=username)
        await message.reply(s["prompt_password"])
        await state.set_state(RegistrationStates.awaiting_password)

async def password_handler(message: types.Message, state: FSMContext, bot: AiogramBot):
    user_tg_id = message.from_user.id
    data = await state.get_data()
    user_lang_code = data.get("user_tg_lang", 'en')
    s = get_tg_strings(user_lang_code)

    # Double check if already registered, e.g., if user restarts flow or races
    if await database.is_telegram_id_registered(user_tg_id):
        await message.reply(s["already_registered_tg"])
        await state.clear()
        return

    password_value = message.text # Password is not stripped by default
    await state.update_data(password=password_value, user_tg_id=user_tg_id) # Store user_tg_id for later use
    
    current_data = await state.get_data() # Re-fetch to get all updated data
    username_value = current_data["name"]

    if config.VERIFY_REGISTRATION:
        global request_id_counter
        request_id_counter += 1
        request_id = request_id_counter
        
        # Store all necessary data for when admin approves/declines
        registration_requests[request_id] = {
            "name": username_value,
            "password": password_value,
            "user_tg_id": user_tg_id,
            "user_tg_lang": user_lang_code,
            "telegram_full_name": message.from_user.full_name # For admin notification
        }
        logger.info(f"Storing registration request ID {request_id} for user {user_tg_id} ({username_value})")


        # Use admin's preferred language for the message to admin
        admin_s = get_tg_strings(get_admin_lang_code())
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=admin_s["admin_approve_button"], callback_data=f"verify_reg:yes:{request_id}"),
             InlineKeyboardButton(text=admin_s["admin_decline_button"], callback_data=f"verify_reg:no:{request_id}")]
        ])
        
        admin_message_text = (
            f"{admin_s['admin_reg_request_header']}\n"
            f"Username: {username_value}\n"
            f"Telegram User: {message.from_user.full_name} (ID: {user_tg_id})\n"
            f"{admin_s['admin_approve_question']}"
        )

        for admin_id_val in config.ADMIN_IDS:
            try:
                await bot.send_message(admin_id_val, admin_message_text, reply_markup=keyboard)
            except Exception as e:
                logger.error(f"Error sending verification request to admin {admin_id_val}: {e}")

        await message.reply(s["reg_request_sent_to_admin"])
        await state.set_state(RegistrationStates.waiting_admin_approval)
    else:
        # Auto-approve: Proceed directly to registration
        source_info = {
            "type": "telegram",
            "telegram_id": user_tg_id,
            "telegram_full_name": message.from_user.full_name,
            "user_lang": user_lang_code
        }
        await _process_actual_registration(user_tg_id, username_value, password_value, source_info, state, bot)


async def admin_verification_handler(callback_query: types.CallbackQuery, state: FSMContext, bot: AiogramBot):
    # state here is the admin's state, which we don't care about for this.
    # We need to manage the user's state if we were to put them back into a flow.
    
    action_parts = callback_query.data.split(':') # verify_reg:yes:1 or verify_reg:no:1
    action = action_parts
    request_id = int(action_parts)

    admin_s = get_tg_strings(get_admin_lang_code()) # For admin's feedback

    pending_reg_data = registration_requests.pop(request_id, None)

    if not pending_reg_data:
        await callback_query.answer(admin_s["admin_req_not_found"], show_alert=True)
        try: await callback_query.message.delete() # Clean up admin message
        except: pass
        return

    # Extract data from the stored request
    username_val = pending_reg_data["name"]
    password_val_cb = pending_reg_data["password"]
    user_tg_id_val = pending_reg_data["user_tg_id"]
    user_tg_lang_val = pending_reg_data.get("user_tg_lang", 'en')
    user_telegram_full_name = pending_reg_data.get("telegram_full_name", "N/A")

    user_s = get_tg_strings(user_tg_lang_val) # For user's notification

    # Check if the user managed to register via another way while waiting
    if await database.is_telegram_id_registered(user_tg_id_val):
        await callback_query.answer(admin_s["admin_user_already_registered_on_approve"], show_alert=True)
        try: # Try to notify user, might fail if bot blocked
            await bot.send_message(user_tg_id_val, user_s["already_registered_tg"])
        except Exception as e:
            logger.warning(f"Could not notify user {user_tg_id_val} about being already registered: {e}")
        try: await callback_query.message.delete()
        except: pass
        return

    # For _process_actual_registration, we need a state object.
    # Since this handler is triggered by admin, user's original state might be gone or irrelevant.
    # We can create a temporary FSMContext or pass None if _process_actual_registration can handle it.
    # For simplicity, we'll pass None for state to _process_actual_registration,
    # and it should clear the state if it receives one, or do nothing if None.
    # Alternatively, create a dummy state for the user:
    # temp_storage = state.storage # if using MemoryStorage, this gives access
    # user_state_for_registration = FSMContext(storage=temp_storage, key=StorageKey(bot_id=bot.id, user_id=user_tg_id_val, chat_id=user_tg_id_val))
    # await user_state_for_registration.set_state(RegistrationStates.awaiting_password) # Or some other logical state
    # For now, _process_actual_registration will clear the passed state.

    if action == "yes":
        await callback_query.answer(admin_s["admin_approved_log"].format(username_val), show_alert=True)
        source_info = {
            "type": "telegram",
            "telegram_id": user_tg_id_val,
            "telegram_full_name": user_telegram_full_name, # Use the stored full name
            "user_lang": user_tg_lang_val,
            "approved_by_admin": callback_query.from_user.id # Log which admin approved
        }
        # We pass None for 'state' because the user's original FSM state might be gone.
        # _process_actual_registration should handle clearing state if one is passed, or ignore if None.
        await _process_actual_registration(user_tg_id_val, username_val, password_val_cb, source_info, None, bot)
        
        try:
            await bot.send_message(user_tg_id_val, user_s["user_approved_notification"])
        except Exception as e:
            logger.warning(f"Could not send approval notification to user {user_tg_id_val}: {e}")
            
    elif action == "no":
        await callback_query.answer(admin_s["admin_declined_log"].format(username_val), show_alert=True)
        try:
            await bot.send_message(user_tg_id_val, user_s["user_declined_notification"])
        except Exception as e:
            logger.warning(f"Could not send decline notification to user {user_tg_id_val}: {e}")
        # No state to clear for the user if we don't create a dummy one.

    try:
        await callback_query.message.edit_reply_markup(reply_markup=None) # Remove buttons
        # Or delete the message: await callback_query.message.delete()
    except Exception as e:
        logger.debug(f"Could not remove buttons from admin message: {e}")


async def _process_actual_registration(
    user_id_val: int,
    username_val: str,
    password_val_reg: str,
    source_info: Dict,
    state: Optional[FSMContext], # User's FSM context, can be None if called post-admin-approval
    bot: AiogramBot
):
    user_lang_code = source_info.get("user_lang", 'en')
    s = get_tg_strings(user_lang_code)

    success, reg_msg_key_or_detail, tt_file_content_val, tt_link_val = \
        await tt_client.perform_teamtalk_registration(username_val, password_val_reg, source_info, bot)

    if success:
        db_add_success = await database.add_telegram_registration(user_id_val, username_val)
        if not db_add_success:
            # This is a critical issue: user registered on TT but not in local DB.
            # Admin should be notified. User might be confused later.
            logger.error(f"CRITICAL: Failed to add Telegram ID {user_id_val} to database for TT user {username_val} after successful TT registration.")
            # Potentially try to inform user of an issue, or ask admin to manually check.
            await bot.send_message(user_id_val, s["reg_failed_admin_or_later"] + " (DB_SYNC_ERROR)")
            # Also inform admins
            admin_notification = f"CRITICAL DB SYNC ERROR: User {username_val} (TG ID: {user_id_val}) registered on TeamTalk BUT FAILED to save to local database. Manual intervention may be required."
            for admin_tg_id in config.ADMIN_IDS:
                try: await bot.send_message(admin_tg_id, admin_notification)
                except: pass

        await bot.send_message(user_id_val, s["reg_success"].format(username_val))

        if tt_file_content_val and tt_link_val:
            tt_file_bytes = bytes(tt_file_content_val, encoding='utf-8')
            
            # Sanitize server name for filename
            safe_server_name_for_file = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in config.SERVER_NAME).rstrip()
            if not safe_server_name_for_file: safe_server_name_for_file = "TeamTalk_Server" # Default filename part
            
            tt_buffered_file = BufferedInputFile(tt_file_bytes, filename=f"{safe_server_name_for_file}_{username_val}.tt")

            try:
                await bot.send_document(user_id_val, document=tt_buffered_file, caption=s["tt_file_caption"])
                await bot.send_message(user_id_val, f"{s['tt_link_caption']}`{tt_link_val}`", parse_mode="Markdown")
            except Exception as e_send:
                logger.error(f"Error sending .tt file or link to user {user_id_val}: {e_send}")
                await bot.send_message(user_id_val, "Could not send the .tt file or link. Please contact an admin.")
    else:
        user_facing_error_message = s["reg_failed_admin_or_later"]
        # reg_msg_key_or_detail might contain specific error details not for user
        if reg_msg_key_or_detail and reg_msg_key_or_detail.startswith("UNEXPECTED_ERROR:"):
            logger.error(f"TT Registration unexpected error for {username_val}: {reg_msg_key_or_detail}")
            # User gets generic message
        elif reg_msg_key_or_detail == "REG_FAILED_SDK_CLIENT":
             logger.error(f"TT Registration client-side SDK error for {username_val}")
        elif reg_msg_key_or_detail == "MODULE_UNAVAILABLE":
             logger.error(f"TT Registration failed for {username_val} because TT module/SDK was unavailable.")

        await bot.send_message(user_id_val, user_facing_error_message)

    if state: # If an FSMContext was passed for the user
        await state.clear()