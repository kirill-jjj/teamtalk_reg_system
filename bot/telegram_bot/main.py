import asyncio
import functools
import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from ..core import config
from ..core.db.session import close_db_engine, init_db
from .handlers.admin import router as admin_router
from .handlers.registration import router as registration_router
from .middlewares.db_middleware import DbSessionMiddleware

logger = logging.getLogger(__name__)


# Startup and Shutdown Handlers
async def on_startup(dispatcher: Dispatcher, db_ready_event: asyncio.Event = None):
    # The dispatcher argument might not be strictly needed for init_db
    # but it's a common signature for startup handlers.
    logger.info("Executing startup actions...")
    await init_db()
    logger.info("Database initialization complete.")
    if db_ready_event:
        db_ready_event.set() # Signal that DB is ready
        logger.info("DB ready event signalled.")

async def on_shutdown(dispatcher: Dispatcher):
    # Similar to on_startup, dispatcher argument might not be needed for close_db_engine
    logger.info("Executing shutdown actions...")
    await close_db_engine()
    logger.info("Database engine closed.")

async def run_telegram_bot(shutdown_handler_callback: callable = None, db_ready_event: asyncio.Event = None):
    bot_instance = AiogramBot(token=config.TG_BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Register DbSessionMiddleware
    dp.update.outer_middleware(DbSessionMiddleware())

    # Register startup and shutdown handlers
    if db_ready_event:
        # Pass the event to the on_startup handler using functools.partial
        dp.startup.register(functools.partial(on_startup, db_ready_event=db_ready_event))
    else:
        # Register without the event if it's not provided (fallback, though run.py should always provide it)
        dp.startup.register(on_startup)
        logger.warning("Running on_startup without db_ready_event. Cleanup task might start prematurely if not coordinated.")

    # Note: The custom shutdown_handler_callback from parameters is also registered to dp.shutdown.
    # Aiogram allows multiple handlers for the same event. They will be called in order of registration.
    # If the custom one needs to run before close_db_engine, it should be registered before on_shutdown.
    # If it needs to run after, it should be registered after.
    # For now, let's register on_shutdown, and the existing custom one will also run.
    dp.shutdown.register(on_shutdown)

    if shutdown_handler_callback:
        # This will be registered in addition to on_shutdown if provided
        dp.shutdown.register(shutdown_handler_callback)
        logger.info("Registered custom shutdown handler for Aiogram dispatcher.")

    dp.include_router(registration_router)
    dp.include_router(admin_router)

    logger.info("Telegram Bot Dispatcher configured with routers. Starting polling...")

    try:
        return bot_instance, dp

    except Exception as e:
        logger.exception("Error during Telegram bot setup (before polling):", exc_info=True)
        raise


async def start_telegram_polling(bot_instance: AiogramBot, dp: Dispatcher):
    try:
        await dp.start_polling(bot_instance, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot_instance.session.close()
        logger.info("Telegram Bot polling stopped and session closed.")


