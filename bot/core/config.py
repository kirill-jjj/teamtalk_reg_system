import os
import logging
from typing import List, Optional, Callable, Any # Added Callable, Any
from dotenv import load_dotenv, find_dotenv

logger = logging.getLogger(__name__)

# Helper functions for parsing environment variables
def _get_env_var(var_name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(var_name, default)

def _get_env_var_bool(var_name: str, default_bool: bool = False) -> bool:
    val_str = os.getenv(var_name)
    if val_str is None:
        return default_bool
    val_lower = val_str.strip().lower()
    if val_lower in ("1", "true", "yes", "on"):
        return True
    if val_lower in ("0", "false", "no", "off"):
        return False
    logger.warning(
        f"Invalid boolean value for environment variable {var_name}: '{val_str}'. "
        f"Using default: {default_bool}."
    )
    return default_bool

def _get_env_var_int(var_name: str, default_int: int) -> int:
    val_str = os.getenv(var_name)
    if val_str is None or not val_str.strip():
        # Also consider empty string as "not set" for integers if default should apply
        return default_int
    try:
        return int(val_str.strip())
    except ValueError:
        logger.warning(
            f"Invalid integer value for environment variable {var_name}: '{val_str}'. "
            f"Using default: {default_int}."
        )
        return default_int

def _get_env_var_list(
    var_name: str,
    default_list_str: Optional[str] = None,
    item_type_converter: Callable[[str], Any] = str
) -> List[Any]:
    val_str = os.getenv(var_name)

    effective_str_to_parse = None
    if val_str is not None: # Env var is set
        effective_str_to_parse = val_str
    elif default_list_str is not None: # Env var not set, but a default string for the list is provided
        effective_str_to_parse = default_list_str
    else: # Env var not set, and no default string provided
        return []

    if not effective_str_to_parse.strip(): # Handles empty string for both val_str and default_list_str
        return []

    items = []
    raw_items = effective_str_to_parse.split(',')
    for item_str in raw_items:
        stripped_item = item_str.strip()
        if not stripped_item: # Skip empty strings resulting from multiple commas like "a,,b"
            continue
        try:
            items.append(item_type_converter(stripped_item))
        except ValueError:
            logger.warning(
                f"Could not convert item '{stripped_item}' to {item_type_converter.__name__} "
                f"for environment variable {var_name}. Skipping this item."
            )
    return items

# --- Constants for Environment Variable Names ---
GENERATED_FILE_TTL_SECONDS_ENV_VAR_NAME: str = "GENERATED_FILE_TTL_SECONDS"
DATABASE_FILE_NAME_ENV_VAR: str = "DB_NAME"
# Moved other _ENV_VAR_NAME constants here
WEB_APP_FORWARDED_ALLOW_IPS_ENV_VAR_NAME: str = "WEB_APP_FORWARDED_ALLOW_IPS"
WEB_APP_PROXY_HEADERS_ENV_VAR_NAME: str = "WEB_APP_PROXY_HEADERS"
TEAMTALK_DEFAULT_USER_RIGHTS_ENV_VAR_NAME: str = "TEAMTALK_DEFAULT_USER_RIGHTS"
REGISTRATION_BROADCAST_ENABLED_ENV_VAR_NAME: str = "TEAMTALK_REGISTRATION_BROADCAST_ENABLED"
FORCE_USER_LANG_ENV_VAR_NAME: str = "FORCE_USER_LANG"
# TeamTalk specific env var names
TT_PUBLIC_HOSTNAME_ENV_VAR_NAME: str = "TT_PUBLIC_HOSTNAME"
TT_JOIN_CHANNEL_ENV_VAR_NAME: str = "TT_JOIN_CHANNEL"
TT_JOIN_CHANNEL_PASSWORD_ENV_VAR_NAME: str = "TT_JOIN_CHANNEL_PASSWORD"
TT_STATUS_TEXT_ENV_VAR_NAME: str = "TT_STATUS_TEXT"
TT_GENDER_ENV_VAR_NAME: str = "TT_GENDER"

# --- Default Fallback Values for Configuration ---
DEFAULT_TTL_SECONDS: int = 600
DEFAULT_DB_NAME: str = "users.db"
DEFAULT_TEAMTALK_USER_RIGHTS_VALUE: str = "MULTI_LOGIN,VIEW_ALL_USERS,CREATE_TEMPORARY_CHANNEL,UPLOAD_FILES,DOWNLOAD_FILES,TRANSMIT_VOICE,TRANSMIT_VIDEOCAPTURE,TRANSMIT_DESKTOP,TRANSMIT_DESKTOPINPUT,TRANSMIT_MEDIAFILE,TEXTMESSAGE_USER,TEXTMESSAGE_CHANNEL"
DEFAULT_REGISTRATION_BROADCAST_ENABLED_VALUE: str = "1" # String "1" as it represents a common env var value for True

# NOTE: The .env file loading is now handled externally (e.g., in run.py)
# before this module's variables are accessed.

# --- Configuration Variable Initialization using Helpers ---
# Telegram Bot Configuration
TG_BOT_TOKEN: Optional[str] = _get_env_var("TG_BOT_TOKEN")
ADMIN_IDS: List[int] = _get_env_var_list("ADMIN_IDS", default_list_str="", item_type_converter=int)

# TeamTalk Server Configuration
HOST_NAME: Optional[str] = _get_env_var("HOST_NAME")
TCP_PORT_STR: Optional[str] = _get_env_var("PORT") # Kept for required_values_from_env check
TCP_PORT: int = _get_env_var_int("PORT", 0)
UDP_PORT: int = _get_env_var_int("UDP_PORT", 0)
if UDP_PORT == 0 and TCP_PORT != 0:
    UDP_PORT = TCP_PORT

USER_NAME: Optional[str] = _get_env_var("USER_NAME")
PASSWORD: Optional[str] = _get_env_var("PASSWORD")
NICK_NAME: str = _get_env_var("NICK_NAME", "RegisterBot")
CLIENT_NAME: str = _get_env_var("CLIENT_NAME", "PyTalkRegisterBot")
ENCRYPTED: bool = _get_env_var_bool("ENCRYPTED", False)
SERVER_NAME: str = _get_env_var("SERVER_NAME", "TeamTalk Server")
DB_NAME_CONFIG: str = _get_env_var(DATABASE_FILE_NAME_ENV_VAR, DEFAULT_DB_NAME)

# TeamTalk Bot Account Specific Configuration
TEAMTALK_PUBLIC_HOSTNAME: Optional[str] = _get_env_var(TT_PUBLIC_HOSTNAME_ENV_VAR_NAME, None)
TEAMTALK_JOIN_CHANNEL: Optional[str] = _get_env_var(TT_JOIN_CHANNEL_ENV_VAR_NAME, None)
TEAMTALK_JOIN_CHANNEL_PASSWORD: str = _get_env_var(TT_JOIN_CHANNEL_PASSWORD_ENV_VAR_NAME, "")
TEAMTALK_STATUS_TEXT: str = _get_env_var(TT_STATUS_TEXT_ENV_VAR_NAME, "")

_raw_gender = _get_env_var(TT_GENDER_ENV_VAR_NAME, "neutral")
_valid_genders = ["male", "female", "neutral"]
if _raw_gender and _raw_gender.lower() in _valid_genders:
    TEAMTALK_GENDER: str = _raw_gender.lower()
else:
    logger.warning(
        f"Invalid value for environment variable {TT_GENDER_ENV_VAR_NAME}: '{_raw_gender}'. "
        f"Using default: 'neutral'."
    )
    TEAMTALK_GENDER: str = "neutral"


# Registration Settings
VERIFY_REGISTRATION: bool = _get_env_var_bool("VERIFY_REGISTRATION", False)
CFG_ADMIN_LANG: str = _get_env_var("BOT_ADMIN_LANG", "en")

# Web Application (FastAPI) Configuration
WEB_REGISTRATION_ENABLED: bool = _get_env_var_bool("WEB_REGISTRATION_ENABLED", False)
WEB_APP_HOST: str = _get_env_var("WEB_APP_HOST", "0.0.0.0")
WEB_APP_PORT_STR: Optional[str] = _get_env_var("WEB_APP_PORT") # Kept for required_values_from_env check
WEB_APP_PORT: int = _get_env_var_int("WEB_APP_PORT", 0)

# Web Application SSL (Optional)
WEB_APP_SSL_ENABLED: bool = _get_env_var_bool("WEB_APP_SSL_ENABLED", False)
WEB_APP_SSL_CERT_PATH: Optional[str] = _get_env_var("WEB_APP_SSL_CERT_PATH")
WEB_APP_SSL_KEY_PATH: Optional[str] = _get_env_var("WEB_APP_SSL_KEY_PATH")

# Web Application Proxy Configuration
# WEB_APP_FORWARDED_ALLOW_IPS_ENV_VAR_NAME and WEB_APP_PROXY_HEADERS_ENV_VAR_NAME moved up
WEB_APP_FORWARDED_ALLOW_IPS_STR: str = _get_env_var(WEB_APP_FORWARDED_ALLOW_IPS_ENV_VAR_NAME, "*")
WEB_APP_FORWARDED_ALLOW_IPS: str | List[str]
if WEB_APP_FORWARDED_ALLOW_IPS_STR == "*":
    WEB_APP_FORWARDED_ALLOW_IPS = "*"
else:
    temp_list = [ip.strip() for ip in WEB_APP_FORWARDED_ALLOW_IPS_STR.split(',') if ip.strip()]
    if not temp_list:
        WEB_APP_FORWARDED_ALLOW_IPS = "*"
        logger.warning(
            f"{WEB_APP_FORWARDED_ALLOW_IPS_ENV_VAR_NAME} was set to an empty or invalid list. "
            f"Defaulting to '*'. Original value: '{WEB_APP_FORWARDED_ALLOW_IPS_STR}'"
        )
    else:
        WEB_APP_FORWARDED_ALLOW_IPS = temp_list

WEB_APP_PROXY_HEADERS: bool = _get_env_var_bool(WEB_APP_PROXY_HEADERS_ENV_VAR_NAME, True)


# TeamTalk Client Template for Web Downloads (Optional)
TEAMTALK_CLIENT_TEMPLATE_DIR: Optional[str] = _get_env_var("TEAMTALK_CLIENT_TEMPLATE_DIR")

# Generated File TTL
GENERATED_FILE_TTL_SECONDS: int = _get_env_var_int(
    GENERATED_FILE_TTL_SECONDS_ENV_VAR_NAME, DEFAULT_TTL_SECONDS
)

# Default TeamTalk User Rights and Registration Broadcast
# ENV_VAR_NAME constants moved up
# DEFAULT_..._VALUE constants moved up

TEAMTALK_DEFAULT_USER_RIGHTS: List[str] = _get_env_var_list(
    TEAMTALK_DEFAULT_USER_RIGHTS_ENV_VAR_NAME,
    default_list_str=DEFAULT_TEAMTALK_USER_RIGHTS_VALUE
)
REGISTRATION_BROADCAST_ENABLED: bool = _get_env_var_bool(
    REGISTRATION_BROADCAST_ENABLED_ENV_VAR_NAME,
    True # Default was "1" (which helper _get_env_var_bool("...", True) handles if env var is "0" or "1" or missing)
)
FORCE_USER_LANG_RAW: Optional[str] = _get_env_var(FORCE_USER_LANG_ENV_VAR_NAME, "")
FORCE_USER_LANG: str = FORCE_USER_LANG_RAW.strip() if FORCE_USER_LANG_RAW else ""


# The old "# --- Parsed and validated values ---" section and the "try-except ValueError" block are now removed
# as parsing is handled by helper functions directly during variable assignment.

# --- Check for required variables ---
# Variables that MUST have a value from the .env file (or environment)
required_values_from_env = {
    "TG_BOT_TOKEN": TG_BOT_TOKEN,
    "HOST_NAME": HOST_NAME,
    "PORT": TCP_PORT_STR, # We check the original string from .env for presence
    "USER_NAME": USER_NAME,
    "PASSWORD": PASSWORD,
    # Add other variables here if they are absolutely mandatory and don't have safe defaults
}
if not ADMIN_IDS: # Example: if at least one admin ID is mandatory
    pass # For now, let it be optional or handle elsewhere

missing_vars = []
for key, value in required_values_from_env.items():
    if value is None or value.strip() == "": # Check for None or empty string
        missing_vars.append(key)

if WEB_REGISTRATION_ENABLED: # Renamed
    if WEB_APP_PORT_STR is None or WEB_APP_PORT_STR.strip() == "": # Renamed
        missing_vars.append("WEB_APP_PORT (when Web registration is enabled)") # Renamed

    if WEB_APP_SSL_ENABLED: # Renamed
        if not WEB_APP_SSL_CERT_PATH: # Renamed
            missing_vars.append("WEB_APP_SSL_CERT_PATH (when SSL is enabled)") # Renamed
        if not WEB_APP_SSL_KEY_PATH: # Renamed
            missing_vars.append("WEB_APP_SSL_KEY_PATH (when SSL is enabled)") # Renamed
    
    # Warning for TEAMTALK_CLIENT_TEMPLATE_DIR validity (not a fatal error for missing_vars)
    if TEAMTALK_CLIENT_TEMPLATE_DIR and not os.path.isdir(TEAMTALK_CLIENT_TEMPLATE_DIR):
        logger.warning(f"TEAMTALK_CLIENT_TEMPLATE_DIR '{TEAMTALK_CLIENT_TEMPLATE_DIR}' is set but not a valid directory. Client ZIP download via Web App may not work.") # Updated log
    elif WEB_REGISTRATION_ENABLED and not TEAMTALK_CLIENT_TEMPLATE_DIR: # Renamed
         logger.info("TEAMTALK_CLIENT_TEMPLATE_DIR is not set. Client download feature via Web App will be unavailable.") # Updated log

if missing_vars:
    unique_missing_vars = sorted(list(set(missing_vars))) # Remove duplicates and sort
    logger.error(f"Missing or invalid required environment variables: {', '.join(unique_missing_vars)}. Please set them in your .env file or environment.")
    exit(1)

# Final check for parsed ports if they were required
if TCP_PORT_STR and TCP_PORT == 0: # If PORT was set in .env but parsed to 0 (e.g., "0" or invalid char then default)
    logger.error("PORT was set in .env but resulted in an invalid TCP_PORT value (0). Please check its value.")

logger.info("Configuration loaded successfully.")