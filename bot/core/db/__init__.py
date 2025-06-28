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
    # PendingWebRegistration CRUD functions
    add_pending_web_registration,
    get_pending_web_registration_by_id,
    get_all_pending_web_registrations,
    remove_pending_web_registration,
    cleanup_expired_pending_web_registrations,
)
from .models import (
    Base,
    FastapiDownloadToken,
    FastapiRegisteredIp,
    PendingTelegramRegistration,
    PendingWebRegistration, # Added PendingWebRegistration model
    TelegramRegistration,
)

# Import key entities from session.py
from .session import AsyncSessionLocal, async_engine, close_db_engine, init_db

# Optional: Define __all__ to specify what gets imported with "from bot.core.db import *"
# This is good practice for packages.
__all__ = [
    "Base",
    "TelegramRegistration",
    "PendingTelegramRegistration",
    "PendingWebRegistration", # Added
    "FastapiRegisteredIp",
    "FastapiDownloadToken",
    "async_engine",
    "AsyncSessionLocal",
    "init_db",
    "close_db_engine",
    "is_telegram_id_registered",
    "add_telegram_registration",
    "get_teamtalk_username_by_telegram_id",
    "add_pending_telegram_registration",
    "get_and_remove_pending_telegram_registration",
    "cleanup_expired_pending_registrations",
    "add_fastapi_registered_ip",
    "is_fastapi_ip_registered",
    "cleanup_expired_registered_ips",
    "add_fastapi_download_token",
    "get_fastapi_download_token",
    "mark_fastapi_download_token_used",
    "remove_fastapi_download_token",
    "cleanup_expired_download_tokens",
    # Added PendingWebRegistration CRUD functions to __all__
    "add_pending_web_registration",
    "get_pending_web_registration_by_id",
    "get_all_pending_web_registrations",
    "remove_pending_web_registration",
    "cleanup_expired_pending_web_registrations",
]
