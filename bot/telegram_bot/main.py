import asyncio
import logging

import pytalk
from aiogram import Bot as AiogramBot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from pytalk.message import Message as PyTalkMessage

from ..core import config, database
from ..core import teamtalk_client as tt_client
from .handlers.admin import router as admin_router
from .handlers.registration import router as registration_router

logger = logging.getLogger(__name__)


@tt_client.pytalk_bot.event
async def on_ready():
    logger.info("PyTalk Bot is ready (event received in telegram_bot.main).")


@tt_client.pytalk_bot.event
async def on_my_login(server: pytalk.server.Server):
    logger.info(f"Successfully logged into TeamTalk server via PyTalk: {server.info.host} (event in telegram_bot.main)")


@tt_client.pytalk_bot.event
async def on_message(message: PyTalkMessage):
    channel_name_info = "DM/Broadcast"
    if hasattr(message, "channel") and message.channel:
        channel_name_info = message.channel.name
    elif isinstance(message, PyTalkMessage) and not hasattr(message, "channel"):
        pass

    logger.info(
        f"Received TeamTalk message via PyTalk: '{message.content}' "
        f"from user '{message.user.username if message.user else 'Unknown User'}' "
        f"in {channel_name_info}"
    )


async def run_telegram_bot(shutdown_handler_callback: callable = None):
    await database.init_db()

    bot_instance = AiogramBot(token=config.TG_BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    if shutdown_handler_callback:
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


async def start_pytalk_bot_internals():
    logger.info("Starting PyTalk bot internal event processing...")
    try:
        async with tt_client.pytalk_bot:
            if not await tt_client.connect_to_teamtalk_server():
                logger.error("Failed to connect to TeamTalk server. PyTalk event processing might not work correctly.")
            await tt_client.pytalk_bot._start()

    except Exception as e:
        logger.exception("Exception in PyTalk bot internal processing loop:", exc_info=True)
    finally:
        logger.info("PyTalk bot internal event processing stopped.")