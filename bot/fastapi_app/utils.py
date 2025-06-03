import asyncio
import os
from pathlib import Path
from fastapi import FastAPI, BackgroundTasks
import logging # Reverted
import aiofiles # Keep aiofiles
import aiofiles.os # Keep aiofiles.os

logger = logging.getLogger(__name__) # Reverted

async def cleanup_temp_file_and_token_task(app_instance: FastAPI, actual_filename_on_server: str, base_dir_name: str, token: str):
    """
    Waits for a delay (implicitly, as it's called after a delay by schedule_temp_file_deletion's caller)
    then deletes the temporary file and its associated token.
    """
    try:
        if base_dir_name == "files":
            base_path = get_generated_files_path(app_instance)
        elif base_dir_name == "zips":
            base_path = get_generated_zips_path(app_instance)
        else:
            logger.error(f"Unknown base_dir_name '{base_dir_name}' for cleanup for token {token}.") # Removed await
            # Remove token to prevent repeated attempts for unknown dir
            if token in app_instance.state.download_tokens:
                del app_instance.state.download_tokens[token]
            return
        file_path = base_path / actual_filename_on_server
        
        if file_path.exists():
            await aiofiles.os.remove(file_path) # Keep await for aiofiles
            logger.info(f"Successfully deleted temporary file: {file_path}") # Removed await
        else:
            logger.warning(f"Temporary file not found for deletion: {file_path}") # Removed await

        # Remove the token from the download_tokens dictionary
        if token in app_instance.state.download_tokens:
            del app_instance.state.download_tokens[token]
            logger.info(f"Successfully deleted token: {token}") # Removed await
        else:
            logger.warning(f"Token not found in download_tokens: {token}") # Removed await

    except Exception as e:
        logger.error(f"Error during cleanup for token {token}, file {actual_filename_on_server}: {e}", exc_info=True) # Removed await


def schedule_temp_file_deletion(
    background_tasks: BackgroundTasks, 
    app_instance: FastAPI, 
    actual_filename_on_server: str, 
    base_dir_name: str,  # e.g., "generated_files" or "generated_zips"
    token: str,
    delay_seconds: int
):
    """
    Schedules a background task to delete a temporary file and its token after a delay.
    """
    async def delayed_cleanup():
        await asyncio.sleep(delay_seconds)
        await cleanup_temp_file_and_token_task(app_instance, actual_filename_on_server, base_dir_name, token)

    background_tasks.add_task(delayed_cleanup)
    logger.info(f"Scheduled cleanup for token {token}, file {actual_filename_on_server} in {delay_seconds}s")


import shutil
import secrets
# import os # For path operations in create_and_save_base_client_zip # This was the targeted one
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import configparser # For modify_teamtalk_ini_from_template
import io # For modify_teamtalk_ini_from_template

from fastapi import FastAPI, Request, BackgroundTasks # Request is for get_user_ip_fastapi

from bot.core import config as core_config # Changed import

# Constants for client ZIP generation
BASE_CLIENT_ZIP_FILENAME = '_base_client_template_fastapi.zip' # Unique name for FastAPI
TEAMTALK_INI_FILENAME_IN_ZIP = "Client/TeamTalk5.ini"
TEAMTALK_INI_FILENAME_LOWER_IN_ZIP = "Client/teamtalk5.ini"


# --- Path Utilities ---
def _get_base_generated_data_path() -> Path:
    """Returns the base path for all generated data."""
    return Path(__file__).resolve().parent.parent.parent / "generated_data_fastapi" # Ensure this is a unique dir

def get_generated_files_path(app: FastAPI) -> Path:
    """Returns the path for generated .tt files."""
    path = _get_base_generated_data_path() / "files"
    return path

def get_generated_zips_path(app: FastAPI) -> Path:
    """Returns the path for generated .zip files."""
    path = _get_base_generated_data_path() / "zips"
    return path

# --- Token and Link Generation ---
def generate_random_token() -> str:
    return secrets.token_hex(16)


# --- INI Modification ---
def get_ini_path_from_template_dir_fastapi(template_dir_base: Path) -> Path | None:
    if not template_dir_base or not template_dir_base.is_dir():
        return None

    ini_path_candidate_upper = template_dir_base / TEAMTALK_INI_FILENAME_IN_ZIP
    ini_path_candidate_lower = template_dir_base / TEAMTALK_INI_FILENAME_LOWER_IN_ZIP

    if ini_path_candidate_upper.exists():
        return ini_path_candidate_upper
    elif ini_path_candidate_lower.exists():
        return ini_path_candidate_lower
    logger.warning(f"TeamTalk5.ini not found in {template_dir_base} at {TEAMTALK_INI_FILENAME_IN_ZIP} or {TEAMTALK_INI_FILENAME_LOWER_IN_ZIP}")
    return None

def modify_teamtalk_ini_from_template(
    template_dir_base: Path, # Expecting Path object
    username: str, password: str,
    server_name_display: str, host: str, tcpport: int, udpport: int, 
    user_client_lang: str # 'en' or 'ru'
) -> str | None:
    ini_template_path = get_ini_path_from_template_dir_fastapi(template_dir_base)
    if not ini_template_path:
        logger.error(f"Error: TeamTalk5.ini template not found in configured TEAMTALK_CLIENT_TEMPLATE_DIR: {template_dir_base}")
        return None

    config = configparser.ConfigParser(interpolation=None, comment_prefixes=(';', '#'), allow_no_value=True)
    config.optionxform = str # Preserve case

    try:
        with open(ini_template_path, 'r', encoding='utf-8-sig') as f:
            config.read_file(f)
    except Exception as e:
        logger.error(f"Error reading INI template {ini_template_path}: {e}", exc_info=True)
        return None

    # Ensure sections exist
    if not config.has_section('general_'): config.add_section('general_')
    if not config.has_section('display'): config.add_section('display')
    if not config.has_section('connection'): config.add_section('connection')
    if not config.has_section('serverentries'): config.add_section('serverentries')

    config.set('general_', 'first-start', 'false')
    config.set('general_', 'nickname', username)
    config.set('display', 'language', 'ru' if user_client_lang == 'ru' else 'en')
    config.set('connection', 'autoconnect', 'true')

    config.set('serverentries', '0_name', server_name_display)
    config.set('serverentries', '0_hostaddr', host)
    config.set('serverentries', '0_tcpport', str(tcpport))
    config.set('serverentries', '0_udpport', str(udpport)) # Assuming core_config.UDP_PORT or similar
    config.set('serverentries', '0_encrypted', 'true' if core_config.ENCRYPTED else 'false') # Corrected
    config.set('serverentries', '0_username', username)
    config.set('serverentries', '0_password', password)
    config.set('serverentries', '0_nickname', username)
    config.set('serverentries', '0_channel', '/')
    if not config.has_option('serverentries', '0_join-last-channel'):
        config.set('serverentries', '0_join-last-channel', 'false')
    if not config.has_option('serverentries', '0_chanpassword'):
        config.set('serverentries', '0_chanpassword', '')
    
    # Explicitly set certificate-related fields
    config.set('serverentries', '0_cadata', '')
    config.set('serverentries', '0_certdata', '')
    config.set('serverentries', '0_keydata', '')
    config.set('serverentries', '0_verifypeer', 'false')

    string_io_buffer = io.StringIO()
    try:
        config.write(string_io_buffer, space_around_delimiters=False)
        return string_io_buffer.getvalue()
    except Exception as e:
        logger.error(f"Error writing INI to string: {e}", exc_info=True)
        return None
    finally:
        string_io_buffer.close()

# --- Client ZIP Creation ---
def create_and_save_base_client_zip(app: FastAPI, template_dir_str: str) -> Path | None:
    """
    Creates a base client ZIP from the template directory and saves it.
    Returns the path to the created base ZIP, or None on failure.
    Uses core_config.TEAMTALK_CLIENT_TEMPLATE_DIR.
    """
    template_dir_base = Path(template_dir_str)
    if not template_dir_base.is_dir():
        logger.error(f"Error: TEAMTALK_CLIENT_TEMPLATE_DIR '{template_dir_str}' not configured or not a directory.")
        return None

    if not get_ini_path_from_template_dir_fastapi(template_dir_base):
        logger.warning(f"No TeamTalk5.ini found in {template_dir_base}/Client/. Base client ZIP creation aborted.")
        return None

    generated_zips_dir = get_generated_zips_path(app) # This already ensures dir exists
    target_zip_path = generated_zips_dir / BASE_CLIENT_ZIP_FILENAME

    try:
        with ZipFile(target_zip_path, 'w', ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(template_dir_base):
                for file_item in files:
                    file_path_item = Path(root) / file_item
                    archive_path = file_path_item.relative_to(template_dir_base)
                    zipf.write(file_path_item, str(archive_path))
        logger.info(f"Base client ZIP created and saved to: {target_zip_path}")
        return target_zip_path
    except Exception as e:
        logger.error(f"Error creating and saving base client ZIP: {e}", exc_info=True)
        if target_zip_path.exists():
            try: target_zip_path.unlink()
            except OSError: pass
        return None

def create_client_zip_for_user(
    app: FastAPI, 
    username: str, 
    password: str, # Added password
    tt_file_name_on_server: str, 
    lang_code: str = "en"
) -> tuple[Path | None, str]:
    """
    Creates a customized client ZIP file for the user by modifying the INI file 
    within the base client ZIP and adding the user's .tt file.
    Returns the path to the new ZIP file and its name, or (None, "") on error.
    """
    base_client_zip_path = Path(app.state.base_client_zip_path_on_disk)
    if not base_client_zip_path.exists():
        logger.error(f"Error: Base client ZIP not found at {base_client_zip_path}")
        return None, ""

    user_tt_file_path = get_generated_files_path(app) / tt_file_name_on_server
    if not user_tt_file_path.exists():
        logger.error(f"Error: User .tt file not found at {user_tt_file_path}")
        return None, ""

    # Create a unique name for the user's ZIP file
    random_suffix = generate_random_token()[:8]
    # Use a more generic name for the user download, actual name on server is unique.
    user_zip_filename_for_download = f"{username}_TeamTalk_config.zip" 
    user_zip_server_name = f"{username}_{core_config.SERVER_NAME}_config_{random_suffix}.zip"
    user_zip_path_final_location = get_generated_zips_path(app) / user_zip_server_name

    # Path to the original client template directory (e.g., "TeamTalk_client_template_EN_RU_portable_v5.9")
    # This is needed by modify_teamtalk_ini_from_template
    client_template_dir = Path(core_config.TEAMTALK_CLIENT_TEMPLATE_DIR)
    if not client_template_dir.is_dir():
        logger.error(f"Error: TEAMTALK_CLIENT_TEMPLATE_DIR '{client_template_dir}' is not a valid directory.")
        return None, ""

    modified_ini_content = modify_teamtalk_ini_from_template(
        template_dir_base=client_template_dir, # Source for INI structure
        username=username,
        password=password,
        server_name_display=core_config.SERVER_NAME, # Corrected
        host=core_config.HOST_NAME,                 # Corrected
        tcpport=core_config.TCP_PORT,               # Corrected
        udpport=core_config.UDP_PORT,               # Corrected (was already correct but good to confirm)
        user_client_lang=lang_code
    )

    if not modified_ini_content:
        logger.error(f"Failed to generate modified INI content for user {username}.")
        return None, ""

    temp_zip_io_buffer = io.BytesIO()
    try:
        with ZipFile(base_client_zip_path, 'r') as base_zip, \
             ZipFile(temp_zip_io_buffer, 'w', ZIP_DEFLATED) as final_zip_out:

            ini_replaced = False
            for item in base_zip.infolist():
                # Normalize path separators for comparison
                item_filename_normalized = item.filename.replace("\\", "/")
                
                if item_filename_normalized.lower() == TEAMTALK_INI_FILENAME_IN_ZIP.lower():
                    # Replace original INI with modified content
                    final_zip_out.writestr(item.filename, modified_ini_content.encode('utf-8-sig'))
                    ini_replaced = True
                else:
                    # Copy other files as they are
                    final_zip_out.writestr(item.filename, base_zip.read(item.filename))
            
            if not ini_replaced:
                # This should ideally not happen if base_client_zip is prepared correctly
                logger.warning(f"INI file '{TEAMTALK_INI_FILENAME_IN_ZIP}' not found in base ZIP. Adding modified INI.")
                final_zip_out.writestr(TEAMTALK_INI_FILENAME_IN_ZIP, modified_ini_content.encode('utf-8-sig'))

            # Add the user's .tt file. Determine target path within ZIP.
            # Example: "Client/username_config.tt" to place it alongside TeamTalk5.ini
            tt_file_path_in_zip = f"Client/{tt_file_name_on_server}"
            final_zip_out.write(user_tt_file_path, tt_file_path_in_zip)

        # Write the new ZIP to its final location
        with open(user_zip_path_final_location, 'wb') as f:
            f.write(temp_zip_io_buffer.getvalue())
        
        return user_zip_path_final_location, user_zip_filename_for_download # Return server path and user-facing name

    except Exception as e:
        logger.error(f"Error creating client ZIP for user {username}: {e}", exc_info=True)
        if user_zip_path_final_location.exists():
            try:
                user_zip_path_final_location.unlink()
            except OSError:
                pass
        return None, ""
    finally:
        temp_zip_io_buffer.close()

# --- User IP Retrieval ---
def get_user_ip_fastapi(request: Request) -> str:
    """Retrieves the user's IP address from the request."""
    # request.client.host can be None if not run behind a proxy that sets X-Forwarded-For
    # or if the server is not configured to use it.
    client_host = request.client.host if request.client else "unknown_ip"
    return client_host
