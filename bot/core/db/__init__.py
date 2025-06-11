# bot/core/db/__init__.py

# Import key entities from models.py to make them available at the db package level
from .models import Base, TelegramRegistration

# Import key entities from session.py
from .session import async_engine, AsyncSessionLocal, init_db, close_db_engine

# Import key entities from crud.py
from .crud import (
    is_telegram_id_registered,
    add_telegram_registration,
    get_teamtalk_username_by_telegram_id
)

# Optional: Define __all__ to specify what gets imported with "from bot.core.db import *"
# This is good practice for packages.
__all__ = [
    "Base",
    "TelegramRegistration",
    "async_engine",
    "AsyncSessionLocal",
    "init_db",
    "close_db_engine",
    "is_telegram_id_registered",
    "add_telegram_registration",
    "get_teamtalk_username_by_telegram_id",
]
