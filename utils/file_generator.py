import os
import secrets
import string
import configparser
import io
from zipfile import ZipFile, ZIP_DEFLATED
from urllib.parse import quote_plus
from typing import Optional, Tuple, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from flask import Flask # For type hinting Flask app instance

logger = logging.getLogger(__name__)

# Constants from flask_registration.py
GENERATED_FILES_DIR_NAME = 'generated_files' # For .tt files
GENERATED_ZIPS_DIR_NAME = 'generated_zips'   # For client .zip files
BASE_CLIENT_ZIP_FILENAME = '_base_client_template.zip'
TEAMTALK_INI_FILENAME_IN_ZIP = "Client/TeamTalk5.ini" # Path within the ZIP
TEAMTALK_INI_FILENAME_LOWER_IN_ZIP = "Client/teamtalk5.ini"


# --- .tt file and TT link generation (from botreg.py) ---
def generate_tt_file_content(server_name_val, host_val, tcpport_val, udpport_val, encrypted_val, username_val, password_val):
    encrypted_str_val = "true" if encrypted_val else "false"
    # Basic XML escaping for username/password in .tt file
    escaped_username = username_val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")
    escaped_password = password_val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE teamtalk>
<teamtalk version="5.0">
 <host>
  <name>{server_name_val}</name>
  <address>{host_val}</address>
  <tcpport>{tcpport_val}</tcpport>
  <udpport>{udpport_val}</udpport>
  <encrypted>{encrypted_str_val}</encrypted>
  <trusted-certificate>
   <certificate-authority-pem></certificate-authority-pem>
   <client-certificate-pem></client-certificate-pem>
   <client-private-key-pem></client-private-key-pem>
   <verify-peer>false</verify-peer>
  </trusted-certificate>
  <auth>
   <username>{escaped_username}</username>
   <password>{escaped_password}</password>
   <nickname>{escaped_username}</nickname>
  </auth>
 </host>
</teamtalk>"""

def generate_tt_link(host_val, tcpport_val, udpport_val, encrypted_val, username_val, password_val):
    encrypted_link_val = "1" if encrypted_val else "0"
    encoded_username = quote_plus(username_val)
    encoded_password = quote_plus(password_val)
    return f"tt://{host_val}?tcpport={tcpport_val}&udpport={udpport_val}&encrypted={encrypted_link_val}&username={encoded_username}&password={encoded_password}&channel=/&chanpasswd="


# --- Client ZIP generation (from flask_registration.py) ---

def get_generated_files_path(app_instance: 'Flask'):
    return os.path.join(app_instance.root_path, GENERATED_FILES_DIR_NAME)

def get_generated_zips_path(app_instance: 'Flask'):
    return os.path.join(app_instance.root_path, GENERATED_ZIPS_DIR_NAME)

def get_ini_path_from_template_dir(template_dir_base: Optional[str]) -> Optional[str]:
    if not template_dir_base or not os.path.isdir(template_dir_base):
        return None

    # TEAMTALK_INI_FILENAME_IN_ZIP is "Client/TeamTalk5.ini"
    # The template dir itself is the root, so we look for Client/TeamTalk5.ini inside it.
    ini_path_candidate_upper = os.path.join(template_dir_base, TEAMTALK_INI_FILENAME_IN_ZIP)
    ini_path_candidate_lower = os.path.join(template_dir_base, TEAMTALK_INI_FILENAME_LOWER_IN_ZIP)


    if os.path.exists(ini_path_candidate_upper):
        return ini_path_candidate_upper
    elif os.path.exists(ini_path_candidate_lower):
        return ini_path_candidate_lower
    logger.warning(f"TeamTalk5.ini not found in {template_dir_base} at {TEAMTALK_INI_FILENAME_IN_ZIP} or {TEAMTALK_INI_FILENAME_LOWER_IN_ZIP}")
    return None

def modify_teamtalk_ini_from_template(
    template_dir_base: str,
    username: str, password: str,
    server_name_display: str, host: str, tcpport: int, udpport: int, encrypted: bool,
    user_client_lang: str # 'en' or 'ru'
) -> Optional[str]:
    ini_template_path = get_ini_path_from_template_dir(template_dir_base)
    if not ini_template_path:
        logger.error(f"TeamTalk5.ini template not found in configured TEAMTALK_CLIENT_TEMPLATE_DIR: {template_dir_base}")
        return None

    config = configparser.ConfigParser(interpolation=None, comment_prefixes=(';', '#'), allow_no_value=True)
    config.optionxform = str # Preserve case

    try:
        # Read with utf-8-sig to handle potential BOM
        with open(ini_template_path, 'r', encoding='utf-8-sig') as f:
            config.read_file(f)
    except Exception as e:
        logger.error(f"Error reading INI template {ini_template_path}: {e}")
        return None

    # Ensure sections exist
    if not config.has_section('general_'): config.add_section('general_')
    if not config.has_section('display'): config.add_section('display')
    if not config.has_section('connection'): config.add_section('connection')
    if not config.has_section('serverentries'): config.add_section('serverentries')

    # Set general settings
    config.set('general_', 'first-start', 'false')
    config.set('general_', 'nickname', username) # Use registered username as nickname

    # Set display language
    config.set('display', 'language', 'ru' if user_client_lang == 'ru' else 'en')

    # Set connection settings
    config.set('connection', 'autoconnect', 'true')

    # Configure the server entry (entry 0)
    config.set('serverentries', '0_name', server_name_display)
    config.set('serverentries', '0_hostaddr', host)
    config.set('serverentries', '0_tcpport', str(tcpport))
    config.set('serverentries', '0_udpport', str(udpport))
    config.set('serverentries', '0_encrypted', 'true' if encrypted else 'false')
    config.set('serverentries', '0_username', username)
    config.set('serverentries', '0_password', password)
    config.set('serverentries', '0_nickname', username) # Also set nickname for the server entry
    config.set('serverentries', '0_channel', '/') # Default to root channel
    if not config.has_option('serverentries', '0_join-last-channel'): # Add if missing
        config.set('serverentries', '0_join-last-channel', 'false')
    if not config.has_option('serverentries', '0_chanpassword'): # Add if missing
        config.set('serverentries', '0_chanpassword', '')


    string_io_buffer = io.StringIO()
    try:
        config.write(string_io_buffer, space_around_delimiters=False)
        return string_io_buffer.getvalue()
    except Exception as e:
        logger.error(f"Error writing INI to string: {e}")
        return None
    finally:
        string_io_buffer.close()

def create_and_save_base_client_zip(app_instance: 'Flask', template_dir_base: str) -> Optional[str]:
    """
    Creates a base client ZIP from the template directory and saves it.
    Returns the path to the created base ZIP, or None on failure.
    """
    if not template_dir_base or not os.path.isdir(template_dir_base):
        logger.error("TEAMTALK_CLIENT_TEMPLATE_DIR not configured or not a directory. Cannot create base client ZIP.")
        return None

    # Ensure the ini file exists in the template, otherwise the base zip is not very useful.
    if not get_ini_path_from_template_dir(template_dir_base):
        logger.error(f"No TeamTalk5.ini found in {template_dir_base}/Client/. Base client ZIP creation aborted.")
        return None

    generated_zips_dir = get_generated_zips_path(app_instance)
    os.makedirs(generated_zips_dir, exist_ok=True)
    target_zip_path = os.path.join(generated_zips_dir, BASE_CLIENT_ZIP_FILENAME)

    try:
        with ZipFile(target_zip_path, 'w', ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(template_dir_base):
                for file_item in files:
                    file_path_item = os.path.join(root, file_item)
                    # archive_path is the path inside the zip, relative to template_dir_base
                    archive_path = os.path.relpath(file_path_item, template_dir_base)
                    zipf.write(file_path_item, archive_path)
        logger.info(f"Base client ZIP created and saved to: {target_zip_path}")
        return target_zip_path
    except Exception as e:
        logger.error(f"Error creating and saving base client ZIP: {e}")
        if os.path.exists(target_zip_path): # Attempt to clean up partially created file
            try: os.remove(target_zip_path)
            except OSError: pass
        return None

def create_client_zip_for_user(
    app_instance: 'Flask',
    base_client_zip_path: str, # Path to the pre-generated base ZIP
    template_dir_base_for_names: str, # Original template dir for naming the output zip
    username: str, password: str,
    server_config_details: dict, # Contains SERVER_NAME_DISPLAY, HOST, TCP_PORT etc.
    user_client_lang: str # 'en' or 'ru'
) -> Optional[Tuple[str, str]]: # (filename_on_server, filename_for_user)
    """
    Creates a user-specific client ZIP by modifying the INI file within the base ZIP.
    Returns (filename_on_server, filename_for_user) or (None, None) on failure.
    """
    if not base_client_zip_path or not os.path.exists(base_client_zip_path):
        logger.error("Base client ZIP is not available or path is invalid. Cannot create user-specific client ZIP.")
        return None, None

    generated_zips_path = get_generated_zips_path(app_instance)
    os.makedirs(generated_zips_path, exist_ok=True) # Ensure dir exists

    template_dir_actual_name = os.path.basename(os.path.normpath(template_dir_base_for_names))
    if not template_dir_actual_name: template_dir_actual_name = "TeamTalkClient"


    random_suffix = secrets.token_hex(4)
    zip_filename_on_server = f"{template_dir_actual_name}_{username}_{random_suffix}.zip"
    zip_filepath_on_server = os.path.join(generated_zips_path, zip_filename_on_server)
    zip_filename_for_user = f"{template_dir_actual_name}_{username}.zip" # User-friendly name

    modified_ini_content_str = modify_teamtalk_ini_from_template(
        os.getenv("TEAMTALK_CLIENT_TEMPLATE_DIR"), # Use the env var for actual path
        username, password,
        server_config_details["SERVER_NAME"], # SERVER_NAME from core.config
        server_config_details["HOST"],
        server_config_details["TCP_PORT"],
        server_config_details["UDP_PORT"],
        server_config_details["ENCRYPTED"],
        user_client_lang
    )

    if modified_ini_content_str is None:
        logger.error(f"Failed to generate modified INI content for user {username}.")
        return None, None

    # Create the new ZIP in memory first, then write to disk
    final_zip_io_buffer = io.BytesIO()
    try:
        with ZipFile(base_client_zip_path, 'r') as base_zip, \
             ZipFile(final_zip_io_buffer, 'w', ZIP_DEFLATED) as final_zip:

            ini_found_and_replaced = False
            for item_info in base_zip.infolist():
                file_content = base_zip.read(item_info.filename)
                normalized_item_name = item_info.filename.replace("\\", "/")

                # Check against both common capitalizations of the INI file path within the zip
                if normalized_item_name.lower() == TEAMTALK_INI_FILENAME_IN_ZIP.lower():
                    final_zip.writestr(item_info.filename, modified_ini_content_str.encode('utf-8-sig')) # Write with BOM
                    ini_found_and_replaced = True
                    logger.debug(f"Replaced INI file '{item_info.filename}' in ZIP for user {username}")
                else:
                    final_zip.writestr(item_info.filename, file_content)

            if not ini_found_and_replaced:
                # This case should ideally not happen if create_and_save_base_client_zip ensures INI exists
                logger.warning(f"INI file not found in base ZIP '{base_client_zip_path}'. Adding modified INI to '{TEAMTALK_INI_FILENAME_IN_ZIP}' for user {username}")
                final_zip.writestr(TEAMTALK_INI_FILENAME_IN_ZIP, modified_ini_content_str.encode('utf-8-sig'))

        # Write the in-memory ZIP to the final file path
        with open(zip_filepath_on_server, 'wb') as f_out:
            f_out.write(final_zip_io_buffer.getvalue())

        logger.info(f"User-specific client ZIP created for {username} at {zip_filepath_on_server}")
        return zip_filename_on_server, zip_filename_for_user

    except Exception as e:
        logger.error(f"Error creating final client ZIP for {username}: {e}")
        if os.path.exists(zip_filepath_on_server): # Attempt cleanup
            try: os.remove(zip_filepath_on_server)
            except OSError: pass
        return None, None
    finally:
        final_zip_io_buffer.close()

def generate_random_token(length_min=12, length_max=30):
    length = secrets.randbelow(length_max - length_min + 1) + length_min
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))