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
    # exit(1) # You might want to handle this more gracefully or ensure defaults

# Telegram Bot Configuration
TG_BOT_TOKEN: Optional[str] = os.getenv("TG_BOT_TOKEN")
ADMIN_IDS_STR: str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: List[int] = [int(id_str.strip()) for id_str in ADMIN_IDS_STR.split(',') if id_str.strip()]

# TeamTalk Server Configuration
HOST_NAME: Optional[str] = os.getenv("HOST_NAME")
TCP_PORT_STR: Optional[str] = os.getenv("PORT")
UDP_PORT_STR: Optional[str] = os.getenv("UDP_PORT", TCP_PORT_STR) # Defaults to TCP_PORT if not set
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
FLASK_PORT_STR: Optional[str] = os.getenv("FLASK_PORT", "5000")
FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "default_secret_key_please_change")

# Flask SSL (Optional)
FLASK_SSL_ENABLED_STR: str = os.getenv("FLASK_SSL_ENABLED", "0")
FLASK_SSL_CERT_PATH: Optional[str] = os.getenv("FLASK_SSL_CERT_PATH")
FLASK_SSL_KEY_PATH: Optional[str] = os.getenv("FLASK_SSL_KEY_PATH")

# TeamTalk Client Template for Flask Downloads (Optional)
TEAMTALK_CLIENT_TEMPLATE_DIR: Optional[str] = os.getenv("TEAMTALK_CLIENT_TEMPLATE_DIR")

# Parsed values and defaults
TCP_PORT: int = 0
UDP_PORT: int = 0
ENCRYPTED: bool = False
VERIFY_REGISTRATION: bool = False
FLASK_REGISTRATION_ENABLED: bool = bool(int(FLASK_REGISTRATION_ENABLED_STR))
FLASK_PORT: int = 0
FLASK_SSL_ENABLED: bool = bool(int(FLASK_SSL_ENABLED_STR))

# Validate and parse integer/boolean variables
try:
    if TCP_PORT_STR:
        TCP_PORT = int(TCP_PORT_STR)
    if UDP_PORT_STR:
        UDP_PORT = int(UDP_PORT_STR)
    else:
        UDP_PORT = TCP_PORT # Default UDP to TCP if UDP_PORT is not explicitly set

    ENCRYPTED = bool(int(ENCRYPTED_STR))
    VERIFY_REGISTRATION = bool(int(VERIFY_REGISTRATION_STR))
    
    if FLASK_REGISTRATION_ENABLED and FLASK_PORT_STR:
        FLASK_PORT = int(FLASK_PORT_STR)

except ValueError as e:
    logger.error(f"Invalid value in environment variables: {e}. Please check your .env file.")
    exit(1)

# Check for required variables
required_telegram = ["TG_BOT_TOKEN", "ADMIN_IDS_STR"]
required_teamtalk = ["HOST_NAME", "PORT", "USER_NAME", "PASSWORD", "NICK_NAME"]
required_settings = ["VERIFY_REGISTRATION_STR", "SERVER_NAME"]

missing_vars = []

for var_name in required_telegram:
    if not globals().get(var_name):
        missing_vars.append(var_name)
for var_name in required_teamtalk:
    if not globals().get(var_name):
        missing_vars.append(var_name)
for var_name in required_settings:
     if globals().get(var_name) is None : # Check for None explicitly for string vars
        missing_vars.append(var_name)


if FLASK_REGISTRATION_ENABLED:
    required_flask = ["FLASK_HOST", "FLASK_PORT_STR", "FLASK_SECRET_KEY"]
    for var_name in required_flask:
        if not globals().get(var_name):
            missing_vars.append(var_name)
    if FLASK_SSL_ENABLED:
        if not FLASK_SSL_CERT_PATH or not FLASK_SSL_KEY_PATH:
            missing_vars.append("FLASK_SSL_CERT_PATH and/or FLASK_SSL_KEY_PATH (when SSL is enabled)")
    if TEAMTALK_CLIENT_TEMPLATE_DIR and not os.path.isdir(TEAMTALK_CLIENT_TEMPLATE_DIR):
        logger.warning(f"TEAMTALK_CLIENT_TEMPLATE_DIR '{TEAMTALK_CLIENT_TEMPLATE_DIR}' is set but not a valid directory. Client ZIP download via Flask may not work.")
    elif FLASK_REGISTRATION_ENABLED and not TEAMTALK_CLIENT_TEMPLATE_DIR:
         logger.info("TEAMTALK_CLIENT_TEMPLATE_DIR is not set. Client download feature via Flask will be unavailable.")


if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}. Please set them in your .env file or environment.")
    exit(1)

if FLASK_REGISTRATION_ENABLED and FLASK_SECRET_KEY == "default_secret_key_please_change":
    logger.warning("FLASK_SECRET_KEY is set to its default value. Please change it to a strong, random secret key for security.")

logger.info("Configuration loaded successfully.")

def get_server_config_for_flask():
    return {
        "SERVER_NAME": SERVER_NAME,
        "HOST": HOST_NAME,
        "TCP_PORT": TCP_PORT,
        "UDP_PORT": UDP_PORT,
        "ENCRYPTED": ENCRYPTED,
        "LANG": ENV_LANG_NUMERIC # For default language on Flask page
    }