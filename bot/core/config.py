import os
import logging
from typing import List, Optional
from dotenv import load_dotenv, find_dotenv

logger = logging.getLogger(__name__)

# Load .env file
dotenv_path = find_dotenv()
if dotenv_path:
    load_dotenv(dotenv_path)
    logger.info(f"Loaded .env file from: {dotenv_path}")
else:
    logger.error("Could not find .env file. Please ensure it exists.")
    # Consider exiting or using hardcoded defaults if .env is critical
    # exit(1)

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
ENV_LANG_NUMERIC: str = os.getenv("LANG", "0") # Bot's default language setting

# Flask Web Registration Configuration
FLASK_REGISTRATION_ENABLED_STR: str = os.getenv("FLASK_REGISTRATION_ENABLED", "0")
FLASK_HOST: str = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT_STR: Optional[str] = os.getenv("FLASK_PORT") # Allow Flask port to be unset if Flask is disabled
FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "default_secret_key_please_change")

# Flask SSL (Optional)
FLASK_SSL_ENABLED_STR: str = os.getenv("FLASK_SSL_ENABLED", "0")
FLASK_SSL_CERT_PATH: Optional[str] = os.getenv("FLASK_SSL_CERT_PATH")
FLASK_SSL_KEY_PATH: Optional[str] = os.getenv("FLASK_SSL_KEY_PATH")

# TeamTalk Client Template for Flask Downloads (Optional)
TEAMTALK_CLIENT_TEMPLATE_DIR: Optional[str] = os.getenv("TEAMTALK_CLIENT_TEMPLATE_DIR")

# --- Parsed and validated values ---
TCP_PORT: int = 0
UDP_PORT: int = 0
ENCRYPTED: bool = False
VERIFY_REGISTRATION: bool = False
FLASK_REGISTRATION_ENABLED: bool = bool(int(FLASK_REGISTRATION_ENABLED_STR)) # Do this early
FLASK_PORT: int = 0
FLASK_SSL_ENABLED: bool = bool(int(FLASK_SSL_ENABLED_STR))

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
    
    if FLASK_REGISTRATION_ENABLED:
        if FLASK_PORT_STR and FLASK_PORT_STR.strip():
            FLASK_PORT = int(FLASK_PORT_STR)
        # If FLASK_PORT_STR is not set while FLASK_REGISTRATION_ENABLED, it will be caught by missing_vars

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
    # logger.warning("ADMIN_IDS is not set. Some admin functionalities might be unavailable.")
    pass # For now, let it be optional or handle elsewhere

missing_vars = []
for key, value in required_values_from_env.items():
    if value is None or value.strip() == "": # Check for None or empty string
        missing_vars.append(key)

if FLASK_REGISTRATION_ENABLED:
    if FLASK_PORT_STR is None or FLASK_PORT_STR.strip() == "":
        missing_vars.append("FLASK_PORT (when Flask is enabled)")
    if FLASK_SECRET_KEY == "default_secret_key_please_change":
        logger.warning("FLASK_SECRET_KEY is set to its default value. Please change it to a strong, random secret key for security.")

    if FLASK_SSL_ENABLED:
        if not FLASK_SSL_CERT_PATH:
            missing_vars.append("FLASK_SSL_CERT_PATH (when SSL is enabled)")
        if not FLASK_SSL_KEY_PATH:
            missing_vars.append("FLASK_SSL_KEY_PATH (when SSL is enabled)")
    
    # Warning for TEAMTALK_CLIENT_TEMPLATE_DIR validity (not a fatal error for missing_vars)
    if TEAMTALK_CLIENT_TEMPLATE_DIR and not os.path.isdir(TEAMTALK_CLIENT_TEMPLATE_DIR):
        logger.warning(f"TEAMTALK_CLIENT_TEMPLATE_DIR '{TEAMTALK_CLIENT_TEMPLATE_DIR}' is set but not a valid directory. Client ZIP download via Flask may not work.")
    elif FLASK_REGISTRATION_ENABLED and not TEAMTALK_CLIENT_TEMPLATE_DIR:
         logger.info("TEAMTALK_CLIENT_TEMPLATE_DIR is not set. Client download feature via Flask will be unavailable.")

if missing_vars:
    unique_missing_vars = sorted(list(set(missing_vars))) # Remove duplicates and sort
    logger.error(f"Missing or invalid required environment variables: {', '.join(unique_missing_vars)}. Please set them in your .env file or environment.")
    exit(1)

# Final check for parsed ports if they were required
if TCP_PORT_STR and TCP_PORT == 0: # If PORT was set in .env but parsed to 0 (e.g., "0" or invalid char then default)
    logger.error("PORT was set in .env but resulted in an invalid TCP_PORT value (0). Please check its value.")
    # exit(1) # This might be too strict if PORT="0" is somehow valid for your TT server.

logger.info("Configuration loaded successfully.")

def get_server_config_for_flask() -> dict:
    """Returns a dictionary of server configurations needed by Flask."""
    return {
        "SERVER_NAME": SERVER_NAME, # Display name from config
        "HOST": HOST_NAME,
        "TCP_PORT": TCP_PORT,
        "UDP_PORT": UDP_PORT,
        "ENCRYPTED": ENCRYPTED,
        "LANG": ENV_LANG_NUMERIC # For default language on Flask page
    }