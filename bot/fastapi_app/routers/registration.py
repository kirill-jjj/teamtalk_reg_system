from fastapi import APIRouter, Request, HTTPException, Depends, Form, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from pathlib import Path
from typing import Optional # Add this line

# Assuming utils.py contains schedule_temp_file_deletion, generate_random_token,
# get_generated_files_path, get_generated_zips_path, generate_tt_file_content, create_client_zip_for_user
from bot.fastapi_app.utils import (
    schedule_temp_file_deletion,
    generate_random_token,
    get_generated_files_path,
    get_generated_zips_path,
    # generate_tt_file_content, # Removed from here
    create_client_zip_for_user, # Added
    get_user_ip_fastapi, # Added
    # generate_tt_link # Removed from here
)
from bot.utils.file_generator import generate_tt_file_content, generate_tt_link # Added new import
from bot.core.localization import get_translator, DEFAULT_LANG_CODE, get_available_languages_for_display
from bot.core.config import FORCE_USER_LANG # Import FORCE_USER_LANG
from bot.core import config as core_config # Changed import
from bot.core import teamtalk_client # Added
import logging # Reverted

logger = logging.getLogger(__name__) # Reverted

router = APIRouter()

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
        _ = get_translator(FORCE_USER_LANG.strip()) # Changed _forced_translator to _
        original_string = "Username:" # Test string for validation
        translated_string = _(original_string) # Updated to _
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
        "title": translator("registration_title"), # Page title
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
    background_tasks: BackgroundTasks, # Added BackgroundTasks
    username: str = Form(...), 
    password: str = Form(...),
    nickname: Optional[str] = Form(None) # Added
):
    if not username or not password:
        # Use translator for error message
        user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE) # Use new name
        translator = get_translator(user_lang_code)
        raise HTTPException(status_code=400, detail=translator("username_password_required_error"))

    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE) # Use new name
    translator = get_translator(user_lang_code)

    # Get user IP
    user_ip = get_user_ip_fastapi(request)

    # Check if IP is already registered (rate limiting)
    if user_ip in request.app.state.registered_ips:
        message = translator("ip_already_registered_error")
        # Render the form again with the error message
        # (Need to pass all template variables again)
        available_languages = get_available_languages_for_display()
        return request.app.state.templates.TemplateResponse("register.html", {
            "request": request,
            "title": translator("registration_title"),
            "message": message,
            "show_form": True,
            "current_lang": user_lang_code,
            "server_name_from_env": request.app.state.cached_server_name,
            "available_languages": available_languages
        }, status_code=400)

    # Check if username already exists (using TeamTalk client)
    try:
        if await teamtalk_client.check_username_exists(username=username):
            message = translator("username_taken_error")
            available_languages = get_available_languages_for_display()
            return request.app.state.templates.TemplateResponse("register.html", {
                "request": request,
                "title": translator("registration_title"),
                "message": message,
                "show_form": True,
                "current_lang": user_lang_code,
                "server_name_from_env": request.app.state.cached_server_name,
                "available_languages": available_languages
            }, status_code=400)
    except Exception as e:
        logger.error(f"Error checking username existence: {e}", exc_info=True) # Removed await
        message = translator("registration_failed_error") # Generic error
        available_languages = get_available_languages_for_display()
        return request.app.state.templates.TemplateResponse("register.html", {
            "request": request,
            "title": translator("registration_title"),
            "message": message,
            "show_form": True,
            "current_lang": user_lang_code,
            "server_name_from_env": request.app.state.cached_server_name,
            "available_languages": available_languages
        }, status_code=500)

    # Perform actual TeamTalk registration
    reg_success_bool = False # Default to false
    source_info_data = {"type": "web", "ip_address": user_ip, "user_lang": user_lang_code}
    if nickname and nickname.strip():
        source_info_data["nickname"] = nickname.strip()
    else:
        source_info_data["nickname"] = username # Default to username if not provided or blank

    try:
        reg_success_bool, _, _, _ = await teamtalk_client.perform_teamtalk_registration(
            username_str=username,
            password_str=password,
            nickname_str=nickname, # Added nickname here
            source_info=source_info_data,
            aiogram_bot_instance=request.app.state.aiogram_bot_instance
            # other params like user_rights_mask, initial_channel_id will use defaults from perform_teamtalk_registration
        )
    except Exception as e:
        logger.error(f"Error during TeamTalk registration for user {username}: {e}", exc_info=True) # Removed await
        reg_success_bool = False # Ensure it's false on exception

    registration_successful = reg_success_bool # Assign to the variable used in subsequent logic

    if not registration_successful:
        message = translator("registration_failed_error")
        available_languages = get_available_languages_for_display()
        return request.app.state.templates.TemplateResponse("register.html", {
            "request": request,
            "title": translator("registration_title"),
            "message": message,
            "show_form": True,
            "current_lang": user_lang_code,
            "server_name_from_env": request.app.state.cached_server_name,
            "available_languages": available_languages
        }, status_code=500)

    # --- Registration successful, proceed to file generation ---
    request.app.state.registered_ips.add(user_ip) # Add user IP to registered set

    # 1. Generate .tt file content
    tt_content = generate_tt_file_content(
        server_name_val=request.app.state.cached_server_name,
        host_val=core_config.HOST_NAME,
        tcpport_val=core_config.TCP_PORT,
        udpport_val=core_config.UDP_PORT,
        encrypted_val=core_config.ENCRYPTED,
        username_val=username,
        password_val=password
    )
    tt_file_name = f"{request.app.state.cached_server_name}.tt" # _config suffix removed
    tt_file_path = get_generated_files_path(request.app) / tt_file_name
    try:
        with open(tt_file_path, "w", encoding="utf-8") as f:
            f.write(tt_content)
    except IOError as e:
        logger.error(f"Failed to write .tt file {tt_file_path}: {e}", exc_info=True) # Removed await
        message = translator("registration_failed_file_error")
        # Potentially un-register user or handle this failure more gracefully
        available_languages = get_available_languages_for_display()
        return request.app.state.templates.TemplateResponse("register.html", {
            "request": request,
            "title": translator("registration_title"),
            "message": message,
            "show_form": True,
            "current_lang": user_lang_code,
            "server_name_from_env": request.app.state.cached_server_name,
            "available_languages": available_languages
        }, status_code=500)

    # 2. Store token for .tt file download
    tt_token = generate_random_token()
    request.app.state.download_tokens[tt_token] = {
        "filename": tt_file_name, 
        "type": "tt_config",
        "original_filename": tt_file_name # For user download
    }
    schedule_temp_file_deletion(
        background_tasks, request.app, tt_file_name, "files", tt_token, 
        delay_seconds=core_config.GENERATED_FILE_TTL_SECONDS
    )
    
    tt_download_link = request.url_for('download_tt_file', token=tt_token)
    # Individual token/filename variables will be used.

    # Initialize variables for client ZIP info, to be populated if ZIP is created
    zip_token: Optional[str] = None
    actual_client_zip_filename_for_user: Optional[str] = None # Renamed from zip_user_filename for clarity

    # 3. Create client ZIP if enabled
    if core_config.TEAMTALK_CLIENT_TEMPLATE_DIR: # Check for template dir presence
        zip_file_path, client_zip_user_download_name = create_client_zip_for_user( # Renamed output var
            app=request.app,
            username=username,
            password=password, # Pass the password
            tt_file_name_on_server=tt_file_name, # Pass the .tt file name that's inside the zip
            lang_code=user_lang_code
        )
        if zip_file_path and client_zip_user_download_name:
            zip_token = generate_random_token() # This is the correct zip_token
            actual_client_zip_filename_for_user = client_zip_user_download_name # Assign here
            request.app.state.download_tokens[zip_token] = {
                "filename": zip_file_path.name, # Actual name on server
                "type": "client_zip",
                "original_filename": actual_client_zip_filename_for_user # Name for user download
            }
            schedule_temp_file_deletion(
                background_tasks, request.app, zip_file_path.name, "zips", zip_token,
                delay_seconds=core_config.GENERATED_FILE_TTL_SECONDS
            )
        else:
            logger.warning(f"Failed to create client ZIP for user {username}") # Removed await
            # Non-critical error, proceed with just .tt file if ZIP fails
    
    # Prepare context for unified registration page in success state
    success_title = translator("registration_successful_title")
    success_message = translator("registration_successful_message")
    tt_quick_link = generate_tt_link(
        host_val=core_config.HOST_NAME,
        tcpport_val=core_config.TCP_PORT,
        udpport_val=core_config.UDP_PORT,
        encrypted_val=core_config.ENCRYPTED,
        username_val=username,
        password_val=password
    )
    available_languages = get_available_languages_for_display() # Also needed for success page if language selector is part of the layout

    return request.app.state.templates.TemplateResponse("register.html", {
        "request": request,
        "title": success_title,
        "message": success_message,
        "message_class": "success",
        "show_form": False,
        "registration_complete": True,
        "current_lang": user_lang_code,
        "server_name_from_env": request.app.state.cached_server_name,
        "available_languages": available_languages,
        "tt_link": tt_quick_link,
        "download_tt_token": tt_token, # This is the token for the .tt file
        "actual_tt_filename_for_user": tt_file_name, # This is the filename for the .tt file
        "download_client_zip_token": zip_token, # Token for client zip, will be None if not created
        "actual_client_zip_filename_for_user": actual_client_zip_filename_for_user # Filename for zip, None if not created
    })


@router.get("/download_tt/{token}")
async def download_tt_file(request: Request, token: str, background_tasks: BackgroundTasks): # Keep background_tasks if used by called functions
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE) # Use new name
    translator = get_translator(user_lang_code)
    token_info = request.app.state.download_tokens.get(token)

    if token_info and token_info.get("type") == "tt_config":
        server_filename = token_info["filename"]
        user_download_filename = token_info.get("original_filename", server_filename)
        file_path = get_generated_files_path(request.app) / server_filename
        if file_path.exists():
            return FileResponse(
                path=file_path, 
                media_type='application/octet-stream', 
                filename=user_download_filename
            )
    raise HTTPException(status_code=404, detail=translator("file_not_found_or_expired_error"))

@router.get("/download_client_zip/{token}")
async def download_client_zip_file(request: Request, token: str, background_tasks: BackgroundTasks): # Keep background_tasks
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE) # Use new name
    translator = get_translator(user_lang_code)
    token_info = request.app.state.download_tokens.get(token)

    if token_info and token_info.get("type") == "client_zip":
        server_filename = token_info["filename"] # This is the name on disk, e.g. user_server_config_random.zip
        user_download_filename = token_info.get("original_filename", server_filename) # This is for user, e.g. user_TeamTalk_config.zip
        file_path = get_generated_zips_path(request.app) / server_filename
        if file_path.exists():
            return FileResponse(
                path=file_path, 
                media_type='application/zip', 
                filename=user_download_filename
            )
    raise HTTPException(status_code=404, detail=translator("file_not_found_or_expired_error"))
