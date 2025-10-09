"""This module contains the main function for running the Telegram bot."""
import logging
from typing import Any

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
import pytalk  # New import

from ..core.config import settings

# Removed close_db_engine, init_db as they are managed by Application
from .handlers.admin import router as admin_router
from .handlers.registration import router as registration_router
from .middlewares.ban_middleware import UserBanMiddleware
from .middlewares.db_middleware import DbSessionMiddleware

logger = logging.getLogger(__name__)


async def run_telegram_bot(
    pytalk_bot_instance: pytalk.TeamTalkBot,
    application: Any,  # Pass the Application instance here
) -> tuple[AiogramBot, Dispatcher]:
    """Initializes and returns the Aiogram bot and dispatcher."""
    bot_instance = AiogramBot(token=settings.tg_bot_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp["dispatcher"] = dp
    dp["pytalk_bot_instance"] = pytalk_bot_instance
    dp["application"] = application  # Store application in context if needed

    # --- REGISTER LIFECYCLE EVENTS ---
    # on_startup will be called before polling starts
    dp.startup.register(application.on_telegram_startup)
    # on_shutdown will be called after polling stops
    dp.shutdown.register(application.on_telegram_shutdown)

    # Register DbSessionMiddleware
    dp.update.outer_middleware(DbSessionMiddleware())

    # Register UserBanMiddleware for message and callback query handlers
    dp.message.outer_middleware(UserBanMiddleware())
    dp.callback_query.outer_middleware(UserBanMiddleware())

    dp.include_router(registration_router)
    dp.include_router(admin_router)

    logger.info(
        "Telegram Bot Dispatcher configured with routers and startup/shutdown hooks."
    )

    return bot_instance, dp


