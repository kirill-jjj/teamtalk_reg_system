import asyncio
import os
import secrets
import shutil
import threading
import logging
from functools import wraps
from typing import Optional, Dict, Set, Tuple, TYPE_CHECKING

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    send_from_directory, current_app, abort, session, Flask
)

from ...core import config as core_config
from ...core import teamtalk_client as tt_client
from ...core.localization import get_translator, DEFAULT_LANG_CODE, refresh_translations
from ...utils.file_generator import (
    generate_tt_file_content, generate_tt_link,
    create_client_zip_for_user,
    get_generated_files_path, get_generated_zips_path,
    GENERATED_FILES_DIR_NAME, GENERATED_ZIPS_DIR_NAME, BASE_CLIENT_ZIP_FILENAME,
    generate_random_token
)
from ...utils.network import get_user_ip_flask

if TYPE_CHECKING:
    from aiogram import Bot as AiogramBot

logger = logging.getLogger(__name__)
flask_bp = Blueprint('web_registration', __name__, template_folder='../templates', static_folder='../static')

_async_loop: Optional[asyncio.AbstractEventLoop] = None
_perform_teamtalk_registration_func = tt_client.perform_teamtalk_registration
_check_username_exists_func = tt_client.check_username_exists

_cached_server_name: str = "TeamTalk Server"
_temp_file_timers: Dict[Tuple[str, str], threading.Timer] = {}
_download_tokens: Dict[str, Dict] = {}
_registered_ips: Set[str] = set()
_base_client_zip_path_on_disk: Optional[str] = None
_aiogram_bot_instance_for_flask: Optional['AiogramBot'] = None

def set_async_loop(loop: asyncio.AbstractEventLoop):
    global _async_loop
    _async_loop = loop

def set_aiogram_bot_instance(bot_instance: 'AiogramBot'):
    global _aiogram_bot_instance_for_flask
    _aiogram_bot_instance_for_flask = bot_instance

def async_task(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _async_loop:
            logger.error("Asyncio event loop not initialized for Flask app.")
            abort(500, description="Server configuration error: Async loop not available.")
        if not _async_loop.is_running():
            logger.warning("Asyncio event loop is not running. Attempting to run a task might fail or hang.")
        future = asyncio.run_coroutine_threadsafe(f(*args, **kwargs), _async_loop)
        try:
            return future.result(timeout=30)
        except asyncio.TimeoutError:
            logger.error(f"Async task {f.__name__} timed out.")
            abort(503, description="Request timed out while processing.")
        except Exception as e:
            logger.exception(f"Exception in async task {f.__name__}: {e}")
            abort(500, description="An internal error occurred.")
    return wrapper

def cleanup_temp_file_and_token(app_instance: Flask, actual_filename_on_server: str, base_dir_name: str):
    global _temp_file_timers, _download_tokens
    logger.debug(f"Cleanup called for {actual_filename_on_server} in {base_dir_name}")
    files_dir_map = {
        GENERATED_FILES_DIR_NAME: get_generated_files_path(app_instance),
        GENERATED_ZIPS_DIR_NAME: get_generated_zips_path(app_instance)
    }
    files_dir = files_dir_map.get(base_dir_name)
    if not files_dir:
        logger.warning(f"Unknown base directory name: {base_dir_name} for file {actual_filename_on_server}")
        return
    filepath = os.path.join(files_dir, actual_filename_on_server)
    try:
        if os.path.exists(filepath) and actual_filename_on_server != BASE_CLIENT_ZIP_FILENAME:
            os.remove(filepath)
            logger.info(f"Removed temporary file: {filepath}")
    except Exception as e:
        logger.error(f"Error removing file {filepath}: {e}")
    finally:
        timer_key = (actual_filename_on_server, base_dir_name)
        _temp_file_timers.pop(timer_key, None)
        tokens_to_remove = [
            token for token, info in list(_download_tokens.items())
            if info.get("filename_on_server") == actual_filename_on_server and info.get("base_dir") == base_dir_name
        ]
        for token in tokens_to_remove:
            _download_tokens.pop(token, None)
            logger.debug(f"Removed download token for {actual_filename_on_server}")

def schedule_temp_file_deletion(app_instance: Flask, actual_filename_on_server: str, base_dir_name: str, delay_seconds=600):
    global _temp_file_timers
    if actual_filename_on_server == BASE_CLIENT_ZIP_FILENAME and base_dir_name == GENERATED_ZIPS_DIR_NAME:
        return
    timer_key = (actual_filename_on_server, base_dir_name)
    if timer_key in _temp_file_timers:
        _temp_file_timers[timer_key].cancel()
    timer = threading.Timer(delay_seconds, cleanup_temp_file_and_token, args=[app_instance, actual_filename_on_server, base_dir_name])
    _temp_file_timers[timer_key] = timer
    timer.start()
    logger.info(f"Scheduled deletion for {actual_filename_on_server} in {delay_seconds}s")

@flask_bp.route('/set_lang/<lang_code>')
def set_language(lang_code):
    if lang_code in ['en', 'ru']:
        session['user_web_lang'] = lang_code
        logger.debug(f"User language set to: {lang_code} in session.")
        refresh_translations()
    return redirect(url_for('.register_page'))

@flask_bp.route('/register', methods=['GET', 'POST'])
@async_task
async def register_page():
    global _cached_server_name, _download_tokens, _registered_ips, _base_client_zip_path_on_disk

    user_web_lang_code = session.get('user_web_lang')
    _ = get_translator(user_web_lang_code if user_web_lang_code else DEFAULT_LANG_CODE)
    current_lang = user_web_lang_code if user_web_lang_code else DEFAULT_LANG_CODE

    if not user_web_lang_code:
        return render_template('choose_lang.html', _=_, server_name_from_env=_cached_server_name)

    template_name = 'register_unified.html'
    user_ip = get_user_ip_flask()

    # Initialize variables for template context
    context = {
        "_": _,
        "message": None,
        "message_class": "info", # Default to 'info'
        "additional_message_info": None,
        "registration_complete": False,
        "show_form": True,
        "tt_link": None,
        "download_tt_token": None,
        "actual_tt_filename_for_user": None,
        "download_client_zip_token": None,
        "actual_client_zip_filename_for_user": None,
        "server_name_from_env": _cached_server_name,
        "request": None, # Will be populated on POST errors if form needs refill
        "current_lang": current_lang
    }

    if not _perform_teamtalk_registration_func or not _check_username_exists_func:
        logger.error("TeamTalk interaction functions are not available to Flask.")
        context["message"] = _("Registration module not fully initialized.")
        context["message_class"] = "error"
        context["show_form"] = False
        return render_template(template_name, **context)

    if user_ip in _registered_ips:
        logger.info(f"IP {user_ip} attempted to register again. Denied.")
        context["message"] = _("An account has already been registered from your IP address. Only one registration per IP is allowed.")
        context["message_class"] = "error"
        context["show_form"] = False
        return render_template(template_name, **context)

    if request.method == 'POST':
        context["request"] = request # For pre-filling form on error
        if user_ip in _registered_ips: # Re-check
            context["message"] = _("An account has already been registered from your IP address. Only one registration per IP is allowed.")
            context["message_class"] = "error"
            context["show_form"] = False
            return render_template(template_name, **context)

        username = request.form.get('username','').strip()
        password = request.form.get('password','')

        if not username or not password:
            context["message"] = _("Username and password are required.")
            context["message_class"] = "error"
        else:
            username_exists = await _check_username_exists_func(username)
            if username_exists is True:
                context["message"] = _("Sorry, this username is already taken. Please choose another username.")
                context["message_class"] = "error"
            elif username_exists is None:
                context["message"] = _("Registration error. Please try again later or contact an administrator.") + " (Username check failed)"
                context["message_class"] = "error"
            else: # Username is available, proceed with registration
                source_info = {"type": "web", "ip_address": user_ip, "user_lang": user_web_lang_code}
                success, reg_msg_key, tt_file_content, tt_link_local = await _perform_teamtalk_registration_func(
                    username, password, source_info, _aiogram_bot_instance_for_flask
                )

                if success:
                    context["message"] = _("User ") + username + _(" successfully registered!")
                    context["message_class"] = "success"
                    context["registration_complete"] = True
                    context["show_form"] = False
                    _registered_ips.add(user_ip)
                    logger.info(f"User {username} successfully registered via web from IP {user_ip}.")
                    context["tt_link"] = tt_link_local

                    current_flask_app_obj = current_app._get_current_object()
                    if tt_file_content:
                        safe_server_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in _cached_server_name).rstrip() or "TeamTalk_Server"
                        filename_on_server = f"{safe_server_name}_{username}_{secrets.token_hex(4)}.tt"
                        context["actual_tt_filename_for_user"] = f"{safe_server_name}.tt"
                        context["download_tt_token"] = generate_random_token()
                        while context["download_tt_token"] in _download_tokens: context["download_tt_token"] = generate_random_token()
                        
                        _download_tokens[context["download_tt_token"]] = {
                            "filename_on_server": filename_on_server,
                            "filename_for_user": context["actual_tt_filename_for_user"],
                            "type": "tt_file", "base_dir": GENERATED_FILES_DIR_NAME
                        }
                        files_dir = get_generated_files_path(current_flask_app_obj)
                        os.makedirs(files_dir, exist_ok=True)
                        with open(os.path.join(files_dir, filename_on_server), 'w', encoding='utf-8') as f: f.write(tt_file_content)
                        schedule_temp_file_deletion(current_flask_app_obj, filename_on_server, GENERATED_FILES_DIR_NAME)

                    if core_config.TEAMTALK_CLIENT_TEMPLATE_DIR and _base_client_zip_path_on_disk:
                        context["additional_message_info"] = _("Please wait, generating client ZIP archive...")
                        server_details = core_config.get_server_config_for_flask()
                        zip_srv_name, zip_usr_name = create_client_zip_for_user(
                            current_flask_app_obj, _base_client_zip_path_on_disk,
                            core_config.TEAMTALK_CLIENT_TEMPLATE_DIR, username, password,
                            server_details, user_web_lang_code
                        )
                        if zip_srv_name and zip_usr_name:
                            context["download_client_zip_token"] = generate_random_token()
                            while context["download_client_zip_token"] in _download_tokens: context["download_client_zip_token"] = generate_random_token()
                            _download_tokens[context["download_client_zip_token"]] = {
                                "filename_on_server": zip_srv_name, "filename_for_user": zip_usr_name,
                                "type": "client_zip", "base_dir": GENERATED_ZIPS_DIR_NAME
                            }
                            context["actual_client_zip_filename_for_user"] = zip_usr_name
                            schedule_temp_file_deletion(current_flask_app_obj, zip_srv_name, GENERATED_ZIPS_DIR_NAME)
                            context["additional_message_info"] = None
                        else:
                            logger.error(f"Failed to create client ZIP for user {username}")
                            context["additional_message_info"] = _("Error creating client ZIP.")
                    elif core_config.TEAMTALK_CLIENT_TEMPLATE_DIR and not _base_client_zip_path_on_disk:
                        context["additional_message_info"] = _("Client ZIP download is currently unavailable.")
                else: # Registration failed
                    context["message_class"] = "error"
                    context["message"] = _("Registration failed. The username might be invalid or an internal error occurred.")
                    if reg_msg_key == "REG_FAILED_SDK_CLIENT" or reg_msg_key == "MODULE_UNAVAILABLE":
                        logger.error(f"Web registration for {username} failed due to: {reg_msg_key}")
                    elif reg_msg_key and reg_msg_key.startswith("UNEXPECTED_ERROR:"):
                         context["message"] = _("An unexpected error occurred during registration: ") # Override generic
                         logger.error(f"Web registration for {username} failed with unexpected error: {reg_msg_key}")
                    else:
                        logger.warning(f"Web registration for {username} failed with message key: {reg_msg_key}")
        # End of username/password/registration logic
        # If form had errors (message is not None and not a success message), keep request for re-fill
        if context["message"] and context["message_class"] == "error":
            pass # request is already set
        else: # Success or no specific error from POST that requires form refill
            context["request"] = None
    # End of POST or GET processing
    return render_template(template_name, **context)

@flask_bp.route('/download_tt/<token>')
def download_tt_file(token):
    global _download_tokens
    file_info = _download_tokens.get(token)
    if not file_info or file_info.get("type") != "tt_file":
        logger.warning(f"Invalid or expired .tt download token received: {token}")
        return abort(404, description="Download link is invalid or has expired.")
    actual_filename_on_server = file_info["filename_on_server"]
    filename_for_user = file_info["filename_for_user"]
    files_dir = get_generated_files_path(current_app._get_current_object())
    filepath = os.path.join(files_dir, actual_filename_on_server)
    if not os.path.exists(filepath):
        logger.warning(f".tt file not found for token {token}: {filepath}")
        _download_tokens.pop(token, None)
        return abort(404, description="File not found or has expired.")
    logger.info(f"Serving .tt file {filename_for_user} (from {actual_filename_on_server}) for token {token}")
    return send_from_directory(files_dir, actual_filename_on_server, as_attachment=True, download_name=filename_for_user)

@flask_bp.route('/download_client_zip/<token>')
def download_client_zip_file(token):
    global _download_tokens
    file_info = _download_tokens.get(token)
    if not file_info or file_info.get("type") != "client_zip":
        logger.warning(f"Invalid or expired client ZIP download token received: {token}")
        return abort(404, description="Client ZIP download link is invalid or has expired.")
    actual_filename_on_server = file_info["filename_on_server"]
    filename_for_user = file_info["filename_for_user"]
    zips_dir = get_generated_zips_path(current_app._get_current_object())
    filepath = os.path.join(zips_dir, actual_filename_on_server)
    if not os.path.exists(filepath):
        logger.warning(f"Client ZIP file not found for token {token}: {filepath}")
        _download_tokens.pop(token, None)
        return abort(404, description="Client ZIP file not found or has expired.")
    logger.info(f"Serving client ZIP {filename_for_user} (from {actual_filename_on_server}) for token {token}")
    return send_from_directory(zips_dir, actual_filename_on_server, as_attachment=True, download_name=filename_for_user)

def initial_flask_app_setup(app: Flask):
    global _cached_server_name, _base_client_zip_path_on_disk
    _cached_server_name = core_config.SERVER_NAME
    generated_files_full_path = get_generated_files_path(app)
    if os.path.exists(generated_files_full_path):
        try: shutil.rmtree(generated_files_full_path)
        except Exception as e: logger.error(f"Error clearing folder {generated_files_full_path}: {e}")
    os.makedirs(generated_files_full_path, exist_ok=True)
    generated_zips_full_path = get_generated_zips_path(app)
    os.makedirs(generated_zips_full_path, exist_ok=True)
    for filename in os.listdir(generated_zips_full_path):
        if filename != BASE_CLIENT_ZIP_FILENAME:
            file_path_to_clean = os.path.join(generated_zips_full_path, filename)
            try:
                if os.path.isfile(file_path_to_clean): os.unlink(file_path_to_clean)
            except Exception as e: logger.warning(f"Error deleting old user zip {file_path_to_clean}: {e}")
    if core_config.TEAMTALK_CLIENT_TEMPLATE_DIR:
        from ...utils.file_generator import create_and_save_base_client_zip
        prospective_base_zip_path = os.path.join(generated_zips_full_path, BASE_CLIENT_ZIP_FILENAME)
        if os.path.exists(prospective_base_zip_path):
            _base_client_zip_path_on_disk = prospective_base_zip_path
            logger.info(f"Found existing base client ZIP: {_base_client_zip_path_on_disk}")
        else:
            logger.info(f"Base client ZIP not found at {prospective_base_zip_path}. Attempting to create new one...")
            created_path = create_and_save_base_client_zip(app, core_config.TEAMTALK_CLIENT_TEMPLATE_DIR)
            if created_path:
                _base_client_zip_path_on_disk = created_path
            else:
                logger.error("Failed to create base client ZIP. Client ZIP download feature will be impaired.")
                _base_client_zip_path_on_disk = None
    else:
        logger.info("TEAMTALK_CLIENT_TEMPLATE_DIR not set, skipping base client ZIP creation.")
        _base_client_zip_path_on_disk = None
    _download_tokens.clear()
    for timer in list(_temp_file_timers.values()): timer.cancel()
    _temp_file_timers.clear()
    _registered_ips.clear()
    logger.info("Flask app initial setup complete. Temporary directories cleaned, base ZIP checked/created.")

def cleanup_flask_resources():
    global _temp_file_timers
    logger.info("Cleaning up Flask resources (canceling timers)...")
    for timer_key in list(_temp_file_timers.keys()):
        timer = _temp_file_timers.pop(timer_key, None)
        if timer:
            timer.cancel()
    logger.info("All pending file deletion timers cancelled.")