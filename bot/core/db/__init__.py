# bot/core/db/__init__.py

# Import key entities from models.py to make them available at the db package level
# Import key entities from crud.py
from .crud import (
    add_fastapi_download_token,
    add_fastapi_registered_ip,
    add_pending_telegram_registration,
    add_telegram_registration,
    cleanup_expired_download_tokens,
    cleanup_expired_pending_registrations,
    cleanup_expired_registered_ips,
    get_and_remove_pending_telegram_registration,
    get_fastapi_download_token,
    get_teamtalk_username_by_telegram_id,
    is_fastapi_ip_registered,
    is_telegram_id_registered,
    mark_fastapi_download_token_used,
    remove_fastapi_download_token,
)
from .models import (
    FastapiDownloadToken,
    FastapiRegisteredIp,
    PendingTelegramRegistration,
    TelegramRegistration,
)

# Import key entities from session.py
from .session import AsyncSessionLocal, async_engine, close_db_engine, init_db

# Optional: Define __all__ to specify what gets imported with "from bot.core.db import *"
# This is good practice for packages.
__all__ = [
    "AsyncSessionLocal",

    "FastapiDownloadToken",      # Added
    "FastapiRegisteredIp",       # Added
    "PendingTelegramRegistration", # Added
    "TelegramRegistration",
    "add_fastapi_download_token",             # Added
    "add_fastapi_registered_ip",              # Added
    "add_pending_telegram_registration",      # Added
    "add_telegram_registration",
    "async_engine",
    "cleanup_expired_download_tokens",         # Added
    "cleanup_expired_pending_registrations",  # Added
    "cleanup_expired_registered_ips",         # Added
    "close_db_engine",
    "get_and_remove_pending_telegram_registration", # Added
    "get_fastapi_download_token",             # Added
    "get_teamtalk_username_by_telegram_id",
    "init_db",
    "is_fastapi_ip_registered",               # Added
    "is_telegram_id_registered",
    "mark_fastapi_download_token_used",       # Added
    "remove_fastapi_download_token"          # Added
]
