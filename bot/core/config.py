import os
import logging
from typing import List, Optional
from dotenv import load_dotenv, find_dotenv

logger = logging.getLogger(__name__)

# --- Constants for Environment Variable Names and Defaults ---
GENERATED_FILE_TTL_SECONDS_ENV_VAR_NAME: str = "GENERATED_FILE_TTL_SECONDS"
DEFAULT_TTL_SECONDS: int = 600

# Load .env file
dotenv_path = find_dotenv()
if dotenv_path:
    load_dotenv(dotenv_path)
    logger.info(f"Loaded .env file from: {dotenv_path}")
else:
    logger.error("Could not find .env file. Please ensure it exists.")
    # Consider exiting or using hardcoded defaults if .env is critical

# Telegram Bot Configuration
TG_BOT_TOKEN: Optional[str] = os.getenv("TG_BOT_TOKEN")
ADMIN_IDS_STR: str = os.getenv("ADMIN_IDS", "") # Default to empty string if not set
ADMIN_IDS: List[int] = [int(id_str.strip()) for id_str in ADMIN_IDS_STR.split(',') if id_str.strip()]

# TeamTalk Server Configuration
HOST_NAME: Optional[str] = os.getenv("HOST_NAME")
TCP_PORT_STR: Optional[str] = os.getenv("PORT")
UDP_PORT_STR: Optional[str] = os.getenv("UDP_PORT") # No default here initially, will default to TCP_PORT later if needed
USER_NAME: Optional[str] = os.getenv("USER_NAME")
PASSWORD: Optional[str] = os.getenv("PASSWORD")
NICK_NAME: str = os.getenv("NICK_NAME", "RegisterBot")
CLIENT_NAME: str = os.getenv("CLIENT_NAME", "PyTalkRegisterBot")
ENCRYPTED_STR: str = os.getenv("ENCRYPTED", "0")
SERVER_NAME: str = os.getenv("SERVER_NAME", "TeamTalk Server")

# Registration Settings
VERIFY_REGISTRATION_STR: str = os.getenv("VERIFY_REGISTRATION", "0")
CFG_ADMIN_LANG: str = os.getenv("LANG", "en")

# Web Application (FastAPI) Configuration
WEB_REGISTRATION_ENABLED_STR: str = os.getenv("WEB_REGISTRATION_ENABLED", "0") # Renamed from FLASK_REGISTRATION_ENABLED
WEB_APP_HOST: str = os.getenv("WEB_APP_HOST", "0.0.0.0") # Renamed from FLASK_HOST
WEB_APP_PORT_STR: Optional[str] = os.getenv("WEB_APP_PORT") # Renamed from FLASK_PORT
# FLASK_SECRET_KEY is not used directly by FastAPI core.

# Web Application SSL (Optional)
WEB_APP_SSL_ENABLED_STR: str = os.getenv("WEB_APP_SSL_ENABLED", "0") # Renamed from FLASK_SSL_ENABLED
WEB_APP_SSL_CERT_PATH: Optional[str] = os.getenv("WEB_APP_SSL_CERT_PATH") # Renamed
WEB_APP_SSL_KEY_PATH: Optional[str] = os.getenv("WEB_APP_SSL_KEY_PATH") # Renamed

# TeamTalk Client Template for Web Downloads (Optional)
TEAMTALK_CLIENT_TEMPLATE_DIR: Optional[str] = os.getenv("TEAMTALK_CLIENT_TEMPLATE_DIR")

# Generated File TTL
GENERATED_FILE_TTL_SECONDS_STR: Optional[str] = os.getenv(
    GENERATED_FILE_TTL_SECONDS_ENV_VAR_NAME, str(DEFAULT_TTL_SECONDS)
)

# Default TeamTalk User Rights and Registration Broadcast
TEAMTALK_DEFAULT_USER_RIGHTS_ENV_VAR_NAME: str = "TEAMTALK_DEFAULT_USER_RIGHTS"
REGISTRATION_BROADCAST_ENABLED_ENV_VAR_NAME: str = "TEAMTALK_REGISTRATION_BROADCAST_ENABLED"

DEFAULT_TEAMTALK_USER_RIGHTS_VALUE: str = "MULTI_LOGIN,VIEW_ALL_USERS,CREATE_TEMPORARY_CHANNEL,UPLOAD_FILES,DOWNLOAD_FILES,TRANSMIT_VOICE,TRANSMIT_VIDEOCAPTURE,TRANSMIT_DESKTOP,TRANSMIT_DESKTOPINPUT,TRANSMIT_MEDIAFILE,TEXTMESSAGE_USER,TEXTMESSAGE_CHANNEL"
DEFAULT_REGISTRATION_BROADCAST_ENABLED_VALUE: str = "1"

TEAMTALK_DEFAULT_USER_RIGHTS_STR: str = os.getenv(TEAMTALK_DEFAULT_USER_RIGHTS_ENV_VAR_NAME, DEFAULT_TEAMTALK_USER_RIGHTS_VALUE)
REGISTRATION_BROADCAST_ENABLED_STR: str = os.getenv(REGISTRATION_BROADCAST_ENABLED_ENV_VAR_NAME, DEFAULT_REGISTRATION_BROADCAST_ENABLED_VALUE)


# --- Parsed and validated values ---
TCP_PORT: int = 0
UDP_PORT: int = 0
ENCRYPTED: bool = False
VERIFY_REGISTRATION: bool = False
WEB_REGISTRATION_ENABLED: bool = bool(int(WEB_REGISTRATION_ENABLED_STR)) # Renamed
WEB_APP_PORT: int = 0 # Renamed
WEB_APP_SSL_ENABLED: bool = bool(int(WEB_APP_SSL_ENABLED_STR)) # Renamed
GENERATED_FILE_TTL_SECONDS: int = DEFAULT_TTL_SECONDS # Initialize with default
TEAMTALK_DEFAULT_USER_RIGHTS: List[str] = []
REGISTRATION_BROADCAST_ENABLED: bool = False

# Validate and parse integer/boolean variables
try:
    if TCP_PORT_STR and TCP_PORT_STR.strip():
        TCP_PORT = int(TCP_PORT_STR)
    # UDP_PORT defaults to TCP_PORT if UDP_PORT_STR is not set or empty
    if UDP_PORT_STR and UDP_PORT_STR.strip():
        UDP_PORT = int(UDP_PORT_STR)
    elif TCP_PORT: # Only default if TCP_PORT was successfully parsed
        UDP_PORT = TCP_PORT
    else: # If TCP_PORT is also 0 (not set or invalid), UDP_PORT remains 0
        UDP_PORT = 0 # This will likely be caught by missing var check if PORT was required

    ENCRYPTED = bool(int(ENCRYPTED_STR))
    VERIFY_REGISTRATION = bool(int(VERIFY_REGISTRATION_STR))
    REGISTRATION_BROADCAST_ENABLED = bool(int(REGISTRATION_BROADCAST_ENABLED_STR))

    TEAMTALK_DEFAULT_USER_RIGHTS = [
        right.strip() for right in TEAMTALK_DEFAULT_USER_RIGHTS_STR.split(',') if right.strip()
    ]
    
    if WEB_REGISTRATION_ENABLED: # Renamed
        if WEB_APP_PORT_STR and WEB_APP_PORT_STR.strip(): # Renamed
            WEB_APP_PORT = int(WEB_APP_PORT_STR) # Renamed
        # If WEB_APP_PORT_STR is not set while WEB_REGISTRATION_ENABLED, it will be caught by missing_vars

    if GENERATED_FILE_TTL_SECONDS_STR and GENERATED_FILE_TTL_SECONDS_STR.strip():
        try:
            GENERATED_FILE_TTL_SECONDS = int(GENERATED_FILE_TTL_SECONDS_STR)
        except ValueError:
            logger.warning(
                f"Invalid value for {GENERATED_FILE_TTL_SECONDS_ENV_VAR_NAME}: "
                f"'{GENERATED_FILE_TTL_SECONDS_STR}'. Using default TTL: {DEFAULT_TTL_SECONDS} seconds."
            )
            GENERATED_FILE_TTL_SECONDS = DEFAULT_TTL_SECONDS # Fallback to default

except ValueError as e:
    logger.error(f"Invalid value in environment variables: {e}. Please check your .env file.")
    exit(1)

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