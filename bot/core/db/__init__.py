# bot/core/db/__init__.py

# Import key entities from models.py to make them available at the db package level
from .models import Base, TelegramRegistration, PendingTelegramRegistration, FastapiRegisteredIp, FastapiDownloadToken

# Import key entities from session.py
from .session import async_engine, AsyncSessionLocal, init_db, close_db_engine

# Import key entities from crud.py
from .crud import (
    is_telegram_id_registered,
    add_telegram_registration,
    get_teamtalk_username_by_telegram_id,
    add_pending_telegram_registration,
    get_and_remove_pending_telegram_registration,
    cleanup_expired_pending_registrations,
    add_fastapi_registered_ip,
    is_fastapi_ip_registered,
    cleanup_expired_registered_ips,
    add_fastapi_download_token,
    get_fastapi_download_token,
    mark_fastapi_download_token_used,
    remove_fastapi_download_token,
    cleanup_expired_download_tokens
)

# Optional: Define __all__ to specify what gets imported with "from bot.core.db import *"
# This is good practice for packages.
__all__ = [
    "Base",
    "TelegramRegistration",
    "PendingTelegramRegistration", # Added
    "FastapiRegisteredIp",       # Added
    "FastapiDownloadToken",      # Added
    "async_engine",
    "AsyncSessionLocal",
    "init_db",
    "close_db_engine",
    "is_telegram_id_registered",
    "add_telegram_registration",
    "get_teamtalk_username_by_telegram_id",
    "add_pending_telegram_registration",      # Added
    "get_and_remove_pending_telegram_registration", # Added
    "cleanup_expired_pending_registrations",  # Added
    "add_fastapi_registered_ip",              # Added
    "is_fastapi_ip_registered",               # Added
    "cleanup_expired_registered_ips",         # Added
    "add_fastapi_download_token",             # Added
    "get_fastapi_download_token",             # Added
    "mark_fastapi_download_token_used",       # Added
    "remove_fastapi_download_token",          # Added
    "cleanup_expired_download_tokens"         # Added
]
