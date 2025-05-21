import asyncio
import logging

from aiogram import Bot as AiogramBot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandObject # For potential future use with command arguments

from .handlers import registration as reg_handlers
from .handlers import admin as admin_handlers # Placeholder for admin commands
from ..core import config, database
from ..core import teamtalk_client as tt_client # Import the core teamtalk client logic
from ..core.localization import get_tg_strings # For pytalk event messages
from pytalk.message import Message as PyTalkMessage # For type hinting
from .states import RegistrationStates # Import states for handler registration

logger = logging.getLogger(__name__)

# Aiogram Bot instance will be created in run_telegram_bot
aiogram_bot: AiogramBot


# --- PyTalk Event Handlers ---
@tt_client.pytalk_bot.event
async def on_ready():
    logger.info("PyTalk Bot is ready (event received in telegram_bot.main).")
    # Connection to TT server is handled by tt_client.connect_to_teamtalk_server()
    # SDK objects are also initialized there after successful connection.
    # No need to duplicate add_server or SDK init here.

@tt_client.pytalk_bot.event
async def on_my_login(server: pytalk.server.Server): # type: ignore
    logger.info(f"Successfully logged into TeamTalk server via PyTalk: {server.info.host} (event in telegram_bot.main)")
    # Additional actions on login can be placed here if needed.

@tt_client.pytalk_bot.event
async def on_message(message: PyTalkMessage):
    # This handles messages *received on the TeamTalk server by the bot*
    # Not to be confused with Telegram messages.
    logger.info(f"Received TeamTalk message via PyTalk: '{message.content}' from user '{message.user.username}' in channel '{message.channel.name if message.channel else 'DM/Broadcast'}'")
    # Example: Echo TT messages to admins via Telegram (can be noisy)
    # admin_lang = get_tg_strings(config.ENV_LANG_NUMERIC) # Or a fixed lang for these alerts
    # for admin_id in config.ADMIN_IDS:
    #     try:
    #         await aiogram_bot.send_message(admin_id, f"TT Msg from {message.user.username}: {message.content}")
    #     except Exception as e:
    #         logger.warning(f"Could not forward TT message to admin {admin_id}: {e}")


# --- Aiogram Bot Setup and Run ---
async def run_telegram_bot():
    global aiogram_bot

    await database.init_db() # Initialize database

    aiogram_bot = AiogramBot(token=config.TG_BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Register handlers
    # Pass the bot instance to handlers that need to send messages
    dp.message.register(
        lambda msg, state: reg_handlers.start_command_handler(msg, state, aiogram_bot),
        Command("start")
    )
    dp.callback_query.register(
        lambda cb_query, state: reg_handlers.language_selection_handler(cb_query, state, aiogram_bot),
        RegistrationStates.choosing_language,
        lambda c: c.data.startswith('set_lang_tg:')
    )
    dp.message.register(
        lambda msg, state: reg_handlers.username_handler(msg, state, aiogram_bot),
        RegistrationStates.awaiting_username
    )
    dp.message.register(
        lambda msg, state: reg_handlers.password_handler(msg, state, aiogram_bot),
        RegistrationStates.awaiting_password
    )
    dp.callback_query.register(
        lambda cb_query, state: reg_handlers.admin_verification_handler(cb_query, state, aiogram_bot),
        # No state for admin verification callback, it acts on stored request_ids
        lambda query: query.data.startswith("verify_reg:")
    )

    admin_handlers.register_admin_handlers(dp) # Register admin command handlers

    logger.info("Telegram Bot Dispatcher configured. Starting polling...")
    
    # Start polling in a way that doesn't block if run with other async tasks
    try:
        await dp.start_polling(aiogram_bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await aiogram_bot.session.close()
        logger.info("Telegram Bot polling stopped and session closed.")
        await database.close_db_engine() # Ensure DB engine is closed when bot stops
        await tt_client.shutdown_pytalk_bot() # Clean up pytalk connections

async def start_pytalk_bot_internals():
    # This function is what pytalk_bot._start() does internally
    # It needs to run in the same event loop as aiogram
    logger.info("Starting PyTalk bot internal event processing...")
    try:
        # Pytalk's context manager handles its loop and cleanup
        async with tt_client.pytalk_bot:
            if not await tt_client.connect_to_teamtalk_server():
                logger.error("Failed to connect to TeamTalk server. PyTalk event processing might not work correctly.")
                # Decide if you want to exit or continue with Telegram bot only
                # For now, we'll let it run, but TT features will be broken.
            
            # The _start() method in pytalk typically runs its own event processing loop.
            # We need to ensure it doesn't block if we are to run aiogram concurrently.
            # If pytalk_bot._start() is blocking, we might need to run it in a separate task
            # and manage its lifecycle.
            # Let's assume pytalk_bot._start() is an async function that processes events
            # when awaited or run in a task.
            await tt_client.pytalk_bot._start() # This should be the non-blocking event processor
            # If it's blocking, this approach needs revision (e.g., asyncio.to_thread for a blocking run)
            
    except Exception as e:
        logger.exception("Exception in PyTalk bot internal processing loop:")
    finally:
        logger.info("PyTalk bot internal event processing stopped.")