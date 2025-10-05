"""This module contains the main function for running the Telegram bot."""
import logging

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
) -> tuple[AiogramBot, Dispatcher]:
    """Initializes and returns the Aiogram bot and dispatcher."""
    bot_instance = AiogramBot(token=settings.tg_bot_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp["dispatcher"] = dp
    dp["pytalk_bot_instance"] = pytalk_bot_instance  # Pass pytalk_bot_instance to dispatcher context

    # Register DbSessionMiddleware
    dp.update.outer_middleware(DbSessionMiddleware())

    # Register UserBanMiddleware for message and callback query handlers
    dp.message.outer_middleware(UserBanMiddleware())
    dp.callback_query.outer_middleware(UserBanMiddleware())

    dp.include_router(registration_router)
    dp.include_router(admin_router)

    logger.info("Telegram Bot Dispatcher configured with routers.")

    return bot_instance, dp


async def start_telegram_polling(bot_instance: AiogramBot, dp: Dispatcher) -> None:
    """Starts the Telegram bot polling."""
    try:
        logger.info("Starting Telegram Bot polling...")
        await dp.start_polling(
            bot_instance, allowed_updates=dp.resolve_used_update_types()
        )
    finally:
        # Bot session closure is now handled by Application.shutdown
        logger.info("Telegram Bot polling stopped.")


