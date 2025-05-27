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
from ...core.localization import get_flask_strings
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

# --- Globals specific to Flask app state ---
_async_loop: Optional[asyncio.AbstractEventLoop] = None
_perform_teamtalk_registration_func = tt_client.perform_teamtalk_registration
_check_username_exists_func = tt_client.check_username_exists

_cached_server_name: str = "TeamTalk Server" # Will be updated from config
_temp_file_timers: Dict[Tuple[str, str], threading.Timer] = {} # (filename_on_server, base_dir_name) -> Timer
_download_tokens: Dict[str, Dict] = {} # token -> {filename_on_server, filename_for_user, type, base_dir}
_registered_ips: Set[str] = set() # Store IPs that have registered in this session
_base_client_zip_path_on_disk: Optional[str] = None # Path to the pre-generated base client ZIP

_aiogram_bot_instance_for_flask: Optional['AiogramBot'] = None

# --- Helper Functions ---
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
            # Consider raising an error or returning a Flask error response
            abort(500, description="Server configuration error: Async loop not available.")
        # Ensure the loop is running, if not, this will error.
        # The loop should be run by the main run.py script.
        if not _async_loop.is_running():
            logger.warning("Asyncio event loop is not running. Attempting to run a task might fail or hang.")
            # This is problematic. Flask runs in its own thread, asyncio in another.
            # Forcing run_coroutine_threadsafe implies the loop is running.

        future = asyncio.run_coroutine_threadsafe(f(*args, **kwargs), _async_loop)
        try:
            return future.result(timeout=30) # Add a timeout to prevent indefinite hanging
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

    if base_dir_name == GENERATED_FILES_DIR_NAME:
        files_dir = get_generated_files_path(app_instance)
    elif base_dir_name == GENERATED_ZIPS_DIR_NAME:
        files_dir = get_generated_zips_path(app_instance)
    else:
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
            token for token, file_info in list(_download_tokens.items())
            if file_info.get("filename_on_server") == actual_filename_on_server and file_info.get("base_dir") == base_dir_name
        ]
        for token in tokens_to_remove:
            _download_tokens.pop(token, None)
            logger.debug(f"Removed download token for {actual_filename_on_server}")

def schedule_temp_file_deletion(app_instance: Flask, actual_filename_on_server: str, base_dir_name: str, delay_seconds=600): # 10 minutes
    global _temp_file_timers
    if actual_filename_on_server == BASE_CLIENT_ZIP_FILENAME and base_dir_name == GENERATED_ZIPS_DIR_NAME:
        return # Do not schedule deletion for the base ZIP

    timer_key = (actual_filename_on_server, base_dir_name)
    if timer_key in _temp_file_timers: # Cancel existing timer if any
        _temp_file_timers[timer_key].cancel()

    timer = threading.Timer(delay_seconds, cleanup_temp_file_and_token, args=[app_instance, actual_filename_on_server, base_dir_name])
    _temp_file_timers[timer_key] = timer
    timer.start()
    logger.info(f"Scheduled deletion for {actual_filename_on_server} in {delay_seconds}s")

# --- Routes ---
@flask_bp.route('/set_lang/<lang_code>')
def set_language(lang_code):
    if lang_code in ['en', 'ru']:
        session['user_web_lang'] = lang_code
        logger.debug(f"User language set to: {lang_code} in session.")
    return redirect(url_for('.register_page'))

@flask_bp.route('/register', methods=['GET', 'POST'])
@async_task # Crucial for calling async TT functions
async def register_page():
    global _cached_server_name, _download_tokens, _registered_ips, _base_client_zip_path_on_disk

    # Determine language for the page
    user_web_lang_code = session.get('user_web_lang') # 'en' or 'ru'
    
    # If no language selected, show chooser. Default to bot's admin lang for chooser page text.
    if not user_web_lang_code:
        # Bot's admin lang preference (0 for en, 1 for ru)
        default_chooser_lang_numeric = core_config.ENV_LANG_NUMERIC
        strings_for_choice = get_flask_strings(default_chooser_lang_numeric)
        return render_template('choose_lang.html',
                               server_name_from_env=_cached_server_name,
                               s=strings_for_choice)

    # Convert 'en'/'ru' to "0"/"1" for get_flask_strings
    display_lang_numeric_str = "1" if user_web_lang_code == 'ru' else "0"
    strings = get_flask_strings(display_lang_numeric_str)
    template_name = 'register_ru.html' if user_web_lang_code == 'ru' else 'register_en.html'
    
    user_ip = get_user_ip_flask()

    if not _perform_teamtalk_registration_func or not _check_username_exists_func:
        logger.error("TeamTalk interaction functions are not available to Flask.")
        return render_template(template_name, message=strings["module_not_initialized"], registration_complete=False, show_form=False, server_name_from_env=_cached_server_name, s=strings)

    # IP-based registration limiting (per session of the Flask app)
    # For persistent IP blocking, a database or a more robust store would be needed.
    if user_ip in _registered_ips:
        logger.info(f"IP {user_ip} attempted to register again. Denied.")
        return render_template(template_name, message=strings["msg_ip_already_registered"], registration_complete=False, show_form=False, server_name_from_env=_cached_server_name, s=strings)

    if request.method == 'POST':
        # Re-check IP on POST as well
        if user_ip in _registered_ips:
            return render_template(template_name, message=strings["msg_ip_already_registered"], registration_complete=False, show_form=False, server_name_from_env=_cached_server_name, s=strings)

        username = request.form.get('username','').strip()
        password = request.form.get('password','') # Do not strip password

        if not username or not password:
            return render_template(template_name, message=strings["msg_required_fields"], registration_complete=False, show_form=True, server_name_from_env=_cached_server_name, s=strings, request=request)

        if await _check_username_exists_func(username):
            return render_template(template_name, message=strings["msg_username_taken"], registration_complete=False, show_form=True, server_name_from_env=_cached_server_name, s=strings, request=request)
        
        source_info = {
            "type": "web",
            "ip_address": user_ip,
            "user_lang": user_web_lang_code # 'en' or 'ru'
        }
        # Pass the aiogram_bot instance for admin notifications
        success, reg_message_key_detail, tt_file_content, tt_link = await _perform_teamtalk_registration_func(
            username, password, source_info, _aiogram_bot_instance_for_flask
        )
        
        display_message = ""
        if success:
            display_message = strings["msg_reg_success_prefix"] + username + strings["msg_reg_success_suffix"]
            _registered_ips.add(user_ip) # Add IP to session-based registered list
            logger.info(f"User {username} successfully registered via web from IP {user_ip}.")
        elif reg_message_key_detail == "REG_FAILED_SDK_CLIENT" or reg_message_key_detail == "MODULE_UNAVAILABLE":
            display_message = strings["msg_reg_failed"] # Generic for these internal issues
            logger.error(f"Web registration for {username} failed due to: {reg_message_key_detail}")
        elif reg_message_key_detail and reg_message_key_detail.startswith("UNEXPECTED_ERROR:"):
            display_message = strings["msg_unexpected_error"] # + reg_message_key_detail.split(":",1) # Avoid exposing too much detail
            logger.error(f"Web registration for {username} failed with unexpected error: {reg_message_key_detail}")
        else: # Generic failure
            display_message = strings["msg_reg_failed"]
            logger.warning(f"Web registration for {username} failed with message key: {reg_message_key_detail}")


        download_tt_token = None
        actual_tt_filename_for_user = None
        download_client_zip_token = None
        actual_client_zip_filename_for_user = None
        additional_message_info = None # For "creating zip..."
        current_flask_app_obj = current_app._get_current_object()


        if success and tt_file_content:
            safe_server_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in _cached_server_name).rstrip() or "TeamTalk_Server"
            
            # .tt file
            actual_tt_filename_on_server = f"{safe_server_name}_{username}_{secrets.token_hex(4)}.tt"
            actual_tt_filename_for_user = f"{safe_server_name}.tt" # User-friendly name
            
            download_tt_token = generate_random_token()
            while download_tt_token in _download_tokens: download_tt_token = generate_random_token()
            
            _download_tokens[download_tt_token] = {
                "filename_on_server": actual_tt_filename_on_server,
                "filename_for_user": actual_tt_filename_for_user,
                "type": "tt_file",
                "base_dir": GENERATED_FILES_DIR_NAME
            }
            files_dir_tt = get_generated_files_path(current_flask_app_obj)
            os.makedirs(files_dir_tt, exist_ok=True)
            filepath_tt = os.path.join(files_dir_tt, actual_tt_filename_on_server)
            with open(filepath_tt, 'w', encoding='utf-8') as f: f.write(tt_file_content)
            schedule_temp_file_deletion(current_flask_app_obj, actual_tt_filename_on_server, GENERATED_FILES_DIR_NAME)

        # Client ZIP generation
        if success and core_config.TEAMTALK_CLIENT_TEMPLATE_DIR and _base_client_zip_path_on_disk:
            additional_message_info = strings["creating_zip_info"]
            server_details_for_ini = core_config.get_server_config_for_flask() # Gets HOST_NAME, TCP_PORT etc.
            
            zip_name_on_server, zip_name_for_user = create_client_zip_for_user(
                current_flask_app_obj,
                _base_client_zip_path_on_disk,
                core_config.TEAMTALK_CLIENT_TEMPLATE_DIR, # Pass original template dir for user-facing zip name
                username, password,
                server_details_for_ini,
                user_web_lang_code
            )

            if zip_name_on_server and zip_name_for_user:
                download_client_zip_token = generate_random_token()
                while download_client_zip_token in _download_tokens: download_client_zip_token = generate_random_token()
                
                _download_tokens[download_client_zip_token] = {
                    "filename_on_server": zip_name_on_server,
                    "filename_for_user": zip_name_for_user,
                    "type": "client_zip",
                    "base_dir": GENERATED_ZIPS_DIR_NAME
                }
                actual_client_zip_filename_for_user = zip_name_for_user
                schedule_temp_file_deletion(current_flask_app_obj, zip_name_on_server, GENERATED_ZIPS_DIR_NAME)
                additional_message_info = None # Clear "creating zip" message
            else:
                logger.error(f"Failed to create client ZIP for user {username}")
                additional_message_info = "Error creating client ZIP." # Update user
        elif success and core_config.TEAMTALK_CLIENT_TEMPLATE_DIR and not _base_client_zip_path_on_disk:
            logger.warning("TEAMTALK_CLIENT_TEMPLATE_DIR is set, but base client ZIP was not found or path is invalid. Skipping client ZIP generation for web user.")
            additional_message_info = "Client ZIP download is currently unavailable."


        return render_template(template_name,
                               message=display_message,
                               additional_message_info=additional_message_info,
                               registration_complete=success,
                               show_form=(not success),
                               tt_link=tt_link if success else None,
                               download_tt_token=download_tt_token if success else None,
                               actual_tt_filename_for_user=actual_tt_filename_for_user if success else None,
                               download_client_zip_token=download_client_zip_token if success else None,
                               actual_client_zip_filename_for_user=actual_client_zip_filename_for_user if success else None,
                               server_name_from_env=_cached_server_name,
                               s=strings,
                               request=request) # Pass request for pre-filling form on error

    # GET request
    return render_template(template_name,
                           registration_complete=False,
                           show_form=True,
                           message=None,
                           server_name_from_env=_cached_server_name,
                           s=strings)


@flask_bp.route('/download_tt/<token>')
def download_tt_file(token):
    global _download_tokens
    file_info = _download_tokens.get(token)

    if not file_info or file_info.get("type") != "tt_file":
        logger.warning(f"Invalid or expired .tt download token received: {token}")
        return abort(404, description="Download link is invalid or has expired.")

    actual_filename_on_server = file_info["filename_on_server"]
    filename_for_user = file_info["filename_for_user"]
    
    current_flask_app_obj = current_app._get_current_object()
    files_dir = get_generated_files_path(current_flask_app_obj)
    filepath = os.path.join(files_dir, actual_filename_on_server)

    if not os.path.exists(filepath):
        logger.warning(f".tt file not found for token {token}: {filepath}")
        _download_tokens.pop(token, None) # Clean up stale token
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
    
    current_flask_app_obj = current_app._get_current_object()
    zips_dir = get_generated_zips_path(current_flask_app_obj)
    filepath = os.path.join(zips_dir, actual_filename_on_server)

    if not os.path.exists(filepath):
        logger.warning(f"Client ZIP file not found for token {token}: {filepath}")
        _download_tokens.pop(token, None) # Clean up stale token
        return abort(404, description="Client ZIP file not found or has expired.")
    
    logger.info(f"Serving client ZIP {filename_for_user} (from {actual_filename_on_server}) for token {token}")
    return send_from_directory(zips_dir, actual_filename_on_server, as_attachment=True, download_name=filename_for_user)

def initial_flask_app_setup(app: Flask):
    """
    Sets up global Flask-related configurations and pre-generates the base client ZIP.
    This should be called once when the Flask app is initialized.
    """
    global _cached_server_name, _base_client_zip_path_on_disk

    _cached_server_name = core_config.SERVER_NAME # Cache for templates

    # Setup temporary file directories
    generated_files_full_path = get_generated_files_path(app)
    if os.path.exists(generated_files_full_path):
        try: shutil.rmtree(generated_files_full_path)
        except Exception as e: logger.error(f"Error clearing folder {generated_files_full_path}: {e}")
    os.makedirs(generated_files_full_path, exist_ok=True)

    generated_zips_full_path = get_generated_zips_path(app)
    os.makedirs(generated_zips_full_path, exist_ok=True)
    
    # Clean up old user-specific ZIPs, but not the base template ZIP
    for filename in os.listdir(generated_zips_full_path):
        if filename != BASE_CLIENT_ZIP_FILENAME:
            file_path_to_clean = os.path.join(generated_zips_full_path, filename)
            try:
                if os.path.isfile(file_path_to_clean): os.unlink(file_path_to_clean)
            except Exception as e: logger.warning(f"Error deleting old user zip {file_path_to_clean}: {e}")

    # Pre-generate or load base client ZIP
    if core_config.TEAMTALK_CLIENT_TEMPLATE_DIR:
        from ...utils.file_generator import create_and_save_base_client_zip # Avoid circular import at top level
        
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

    # Clear any stale in-memory trackers
    _download_tokens.clear()
    for timer in list(_temp_file_timers.values()): timer.cancel()
    _temp_file_timers.clear()
    _registered_ips.clear()
    logger.info("Flask app initial setup complete. Temporary directories cleaned, base ZIP checked/created.")

def cleanup_flask_resources():
    """Call this on application shutdown to cancel timers."""
    global _temp_file_timers
    logger.info("Cleaning up Flask resources (canceling timers)...")
    for timer_key in list(_temp_file_timers.keys()):
        timer = _temp_file_timers.pop(timer_key, None)
        if timer:
            timer.cancel()
    logger.info("All pending file deletion timers cancelled.")