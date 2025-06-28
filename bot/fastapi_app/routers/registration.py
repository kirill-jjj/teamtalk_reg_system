import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pytalk.enums import UserType as PyTalkUserType
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core import config as core_config
from bot.core.config import FORCE_USER_LANG
from bot.core.db import (
    add_fastapi_download_token,
    add_fastapi_registered_ip,
    get_fastapi_download_token,
    is_fastapi_ip_registered,
    mark_fastapi_download_token_used,
    add_pending_web_registration, # New import for pending web registration
)
from bot.core.localization import (
    DEFAULT_LANG_CODE,
    get_admin_lang_code,
    get_available_languages_for_display,
    get_translator,
)

# Assuming utils.py contains schedule_temp_file_deletion, generate_random_token,
# get_generated_files_path, get_generated_zips_path, generate_tt_file_content, create_client_zip_for_user
from bot.fastapi_app.utils import (
    create_client_zip_for_user,
    generate_random_token,
    get_generated_files_path,
    get_generated_zips_path,
    get_user_ip_fastapi,
    schedule_temp_file_deletion,
)
from bot.teamtalk import users as teamtalk_users_service
# from bot.utils.file_generator import generate_tt_file_content, generate_tt_link # No longer needed here

# Import DB dependency and CRUD functions
from ..dependencies import get_db_session

# For admin notifications
import secrets # For generating request_key
from aiogram import Bot as AiogramBot
from bot.core.config import ADMIN_IDS, TG_BOT_TOKEN # For notifying admins

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize Aiogram Bot instance for notifications
# This assumes TG_BOT_TOKEN is correctly set in the environment / config
# A better approach for a large app might be to have a shared bot instance,
# but for this specific task, initializing it here is acceptable.
# Ensure this is handled carefully in production (e.g., lifecycle management if needed).
# bot_instance_for_notification = AiogramBot(token=TG_BOT_TOKEN)
# ^^ This might be problematic if the bot is already running elsewhere.
# A safer way is to get the bot instance from the request's app state if it's stored there,
# or use a dependency injection system. For now, we'll assume a helper or direct init.
# Let's assume the bot instance is available via request.app.state.bot if set up in main.py
# For simplicity in this focused change, we might have to pass it or initialize it.
# Given the current structure, direct initialization is the most straightforward path
# without larger refactoring of how the bot instance is shared with FastAPI.

# Helper function for validation
async def _validate_web_registration_request(
    request: Request,
    username: str,
    password: str,
    user_ip: str,
    translator,
    db: AsyncSession
) -> Optional[HTTPException]:
    # Check for empty username/password
    if not username or not password:
        logger.warning(f"Validation failed for IP {user_ip}: Empty username or password.")
        return HTTPException(status_code=400, detail=translator("username_password_required_error"))

    # Check if IP is already registered (rate limiting) using database
    if await is_fastapi_ip_registered(db, user_ip):
        logger.warning(f"Validation failed for IP {user_ip} (Username: {username}): IP already registered.")
        return HTTPException(status_code=400, detail=translator("ip_already_registered_error"))

    # Check if username already exists
    try:
        username_exists = await teamtalk_users_service.check_username_exists(username=username)
        if username_exists is True:
            logger.warning(f"Validation failed for IP {user_ip} (Username: {username}): Username already taken.")
            return HTTPException(status_code=400, detail=translator("username_taken_error"))
        elif username_exists is None: # Indicates an error during the check
            logger.error(f"Validation failed for IP {user_ip} (Username: {username}): check_username_exists returned None (error).")
            return HTTPException(status_code=500, detail=translator("registration_failed_error"))
    except Exception as e:
        logger.error(f"Exception during username existence check for {username} (IP: {user_ip}): {e}", exc_info=True)
        return HTTPException(status_code=500, detail=translator("registration_failed_error"))

    return None # All validations passed

# _execute_tt_registration_for_web and _prepare_downloadables_for_web are removed as web registration
# will now go into a pending state and be processed by admins. File generation will occur
# after approval, likely triggered by the admin approval action.

@router.post("/set_lang_and_reload")
async def set_language_and_reload(request: Request, lang_code: str = Form(...)):
    response = RedirectResponse(url=request.url_for('register_page_get'), status_code=302)
    response.set_cookie(key="user_web_lang", value=lang_code)
    return response

@router.get("/register")
async def register_page_get(request: Request):
    effective_lang_code = DEFAULT_LANG_CODE
    language_is_forced = False

    if FORCE_USER_LANG and FORCE_USER_LANG.strip():
        _ = get_translator(FORCE_USER_LANG.strip())
        original_string = "Username:" # Test string for validation
        translated_string = _(original_string)
        if translated_string != original_string:
            effective_lang_code = FORCE_USER_LANG.strip()
            language_is_forced = True # Used to decide if we should even check cookies
            logger.info(f"Web: Language forced to {effective_lang_code} by config.")
        else:
            logger.warning(f"Web: FORCE_USER_LANG set to '{FORCE_USER_LANG.strip()}' but seems invalid/incomplete. Falling back.")
            # Fallback to cookie or default
            effective_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
    else:
        # No force, use cookie or default
        effective_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)

    translator = get_translator(effective_lang_code)
    available_languages = get_available_languages_for_display()
    
    # Prepare context for the template.
    # The global context processor already adds 'current_lang' and 'language_forced'.
    # We set 'current_lang' here mainly for any direct use within this function,
    # and to ensure the template has it if the global context processor was bypassed,
    # though with Jinja2, the global one should take precedence or be the one used.
    # The template will decide whether to show language selection or the form.
    context = {
        "request": request,
        "title": translator("registration_title"),
        "message": "", 
        "show_form": True, # Main form is now always shown initially, template handles visibility post-registration
        "current_lang": effective_lang_code, # Reflects forced or cookie lang
        "server_name_from_env": request.app.state.cached_server_name,
        "available_languages": available_languages,
        # 'language_forced' will be available globally from the context_processor.
        # Ensure other necessary variables for the template are included if it's a success page,
        # but for initial GET or after lang set, these might not be relevant.
        # The existing POST /register handler populates these for success/error states.
        "registration_complete": False, # Default for initial GET
        "tt_link": None,
        "download_tt_token": None,
        "actual_tt_filename_for_user": None,
        "download_client_zip_token": None,
        "actual_client_zip_filename_for_user": None
    }
    return request.app.state.templates.TemplateResponse("register.html", context)

@router.post("/register")
async def register_page_post(
    request: Request,
    background_tasks: BackgroundTasks,
    username: str = Form(...),
    password: str = Form(...),
    nickname: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db_session)
):
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
    translator = get_translator(user_lang_code)
    user_ip = get_user_ip_fastapi(request)
    user_agent = request.headers.get("user-agent", "N/A")

    validation_error = await _validate_web_registration_request(
        request, username, password, user_ip, translator, db
    )

    if validation_error:
        available_languages = get_available_languages_for_display()
        return request.app.state.templates.TemplateResponse("register.html", {
            "request": request,
            "title": translator("registration_title"),
            "message": validation_error.detail,
            "show_form": True, # Keep form visible for corrections
            "current_lang": user_lang_code,
            "server_name_from_env": request.app.state.cached_server_name,
            "available_languages": available_languages,
            "username_value": username, # Preserve entered username
            "nickname_value": nickname   # Preserve entered nickname
        }, status_code=validation_error.status_code)

    # --- Validation successful, proceed to save as pending ---
    final_nickname = nickname if nickname and nickname.strip() else username
    request_key = secrets.token_urlsafe(32) # Generate a unique key for this request

    source_info_data = {
        "type": "web_pending_approval", # New type
        "ip_address": user_ip,
        "user_agent": user_agent,
        "user_lang": user_lang_code,
        "nickname_chosen_by_user": nickname if nickname and nickname.strip() else None, # Store original choice
        # Any other relevant info from the request can be added here
    }

    try:
        await add_pending_web_registration(
            db=db,
            request_key=request_key,
            username=username,
            password_cleartext=password, # Storing password temporarily until approval
            nickname=final_nickname, # This is what will be used if approved
            ip_address=user_ip,
            user_agent=user_agent,
            source_info=source_info_data
        )
        logger.info(f"Pending web registration for user '{username}' (IP: {user_ip}) saved with request key {request_key}.")

        # Record the IP as having submitted a registration request (for rate limiting future *pending* requests)
        try:
            await add_fastapi_registered_ip(db, ip_address=user_ip, username=f"pending_{username}")
        except Exception as e_ip_add:
            logger.error(f"Failed to add/update registered IP {user_ip} for pending user {username} to DB: {e_ip_add}", exc_info=True)
            # Continue, as this is not fatal for the pending registration itself.

        # Notify admins
        if ADMIN_IDS and TG_BOT_TOKEN:
            # It's better to get the bot instance from app state if available, e.g., request.app.state.bot
            # Fallback to initializing a new one for notification if not found.
            bot_for_notification = getattr(request.app.state, "bot", None)
            if not bot_for_notification:
                logger.info("No shared bot instance found in app.state.bot, initializing new one for admin notification.")
                bot_for_notification = AiogramBot(token=TG_BOT_TOKEN)

            admin_message = (
                f"📢 New Web Registration Pending Approval 📢\n\n"
                f"Username: `{username}`\n"
                f"Nickname: `{final_nickname}`\n"
                f"IP Address: `{user_ip}`\n"
                f"User Agent: `{user_agent[:100]}{'...' if len(user_agent) > 100 else ''}`\n\n" # Truncate user agent
                f"Please review in the admin panel."
            )
            for admin_id_str in ADMIN_IDS:
                try:
                    admin_id = int(admin_id_str)
                    await bot_for_notification.send_message(chat_id=admin_id, text=admin_message, parse_mode="Markdown")
                except ValueError:
                    logger.error(f"Invalid admin ID for notification: {admin_id_str}")
                except Exception as e_notify:
                    logger.error(f"Failed to send web registration notification to admin {admin_id_str}: {e_notify}")

            # If bot was initialized here, close it if possible (though send_message might handle it)
            # For a shared bot, this is not needed.
            if not getattr(request.app.state, "bot", None) and bot_for_notification:
                 # Check if session attribute exists and try to close, new aiogram might not need explicit close after send
                if hasattr(bot_for_notification, 'session') and bot_for_notification.session:
                    await bot_for_notification.session.close()


        # Inform user their request is pending
        pending_approval_title = translator("registration_pending_title")
        pending_approval_message = translator("registration_pending_message")
        available_languages = get_available_languages_for_display()

        final_context = {
            "request": request,
            "title": pending_approval_title,
            "message": pending_approval_message,
            "message_class": "info", # Use a different class for pending status
            "show_form": False, # Hide form, show pending message
            "registration_complete": False, # Not complete, but pending
            "registration_pending": True, # New flag for template
            "current_lang": user_lang_code,
            "server_name_from_env": request.app.state.cached_server_name,
            "available_languages": available_languages,
        }
        return request.app.state.templates.TemplateResponse("register.html", final_context)

    except Exception as e_pending:
        logger.error(f"Failed to save pending web registration for user '{username}' (IP: {user_ip}): {e_pending}", exc_info=True)
        message = translator("registration_failed_error") # Generic error for user
        available_languages = get_available_languages_for_display()
        return request.app.state.templates.TemplateResponse("register.html", {
            "request": request,
            "title": translator("registration_title"),
            "message": message,
            "show_form": True,
            "current_lang": user_lang_code,
            "server_name_from_env": request.app.state.cached_server_name,
            "available_languages": available_languages,
            "username_value": username,
            "nickname_value": nickname
        }, status_code=500)


@router.get("/download_tt/{token}")
async def download_tt_file(
    request: Request, token: str,
    db: AsyncSession = Depends(get_db_session)
):
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
    translator = get_translator(user_lang_code)

    token_info_model = await get_fastapi_download_token(db, token)

    if token_info_model and token_info_model.token_type == "tt_config":
        # get_fastapi_download_token already checks expiry and is_used
        server_filename = token_info_model.filepath_on_server # This is just the filename
        user_download_filename = token_info_model.original_filename
        file_path = get_generated_files_path(request.app) / server_filename

        if file_path.exists():
            await mark_fastapi_download_token_used(db, token)
            return FileResponse(
                path=file_path,
                media_type='application/octet-stream',
                filename=user_download_filename
            )
    raise HTTPException(status_code=404, detail=translator("file_not_found_or_expired_error"))

@router.get("/download_client_zip/{token}")
async def download_client_zip_file(
    request: Request, token: str,
    db: AsyncSession = Depends(get_db_session)
):
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
    translator = get_translator(user_lang_code)

    token_info_model = await get_fastapi_download_token(db, token)

    if token_info_model and token_info_model.token_type == "client_zip":
        # get_fastapi_download_token already checks expiry and is_used
        server_filename = token_info_model.filepath_on_server # This is just the filename
        user_download_filename = token_info_model.original_filename
        file_path = get_generated_zips_path(request.app) / server_filename

        if file_path.exists():
            await mark_fastapi_download_token_used(db, token)
            return FileResponse(
                path=file_path,
                media_type='application/zip',
                filename=user_download_filename
            )
    raise HTTPException(status_code=404, detail=translator("file_not_found_or_expired_error"))
