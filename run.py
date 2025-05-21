import asyncio
import logging
import threading # For running Flask in a separate thread

from teamtalk_reg_system.core import config as core_config # Ensure config is loaded first
from teamtalk_reg_system.telegram_bot.main import run_telegram_bot, start_pytalk_bot_internals, aiogram_bot as global_aiogram_bot_instance
from teamtalk_reg_system.web_app.main import create_flask_app, run_flask_app
from teamtalk_reg_system.core.database import close_db_engine # For graceful shutdown
from teamtalk_reg_system.core.teamtalk_client import shutdown_pytalk_bot # For graceful shutdown

# --- Logging Configuration ---
# Basic logging setup, can be expanded (e.g., to file, richer format)
logging.basicConfig(
    level=logging.INFO, # Adjust as needed (e.g., logging.DEBUG for more verbosity)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler() # Log to console
        # You can add logging.FileHandler("app.log") here
    ]
)
# Reduce verbosity of some libraries if needed
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("pytalk").setLevel(logging.INFO) # Adjust pytalk's own logging
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING) # Example for noisy lib

logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting application...")

    # Initialize Aiogram Bot (this also initializes the global_aiogram_bot_instance)
    # The run_telegram_bot itself will start polling. We need the instance for Flask.
    # A bit of a chicken-and-egg, so we'll rely on run_telegram_bot populating the global.
    # A cleaner way might be to have run_telegram_bot return the bot instance,
    # but for now, this mirrors the existing structure of aiogram_bot becoming available.
    
    # Tasks to run concurrently
    tasks = []

    # Task for Telegram bot polling and PyTalk internal processing
    # These are tightly coupled with the asyncio loop
    telegram_task = asyncio.create_task(run_telegram_bot(), name="TelegramBotPolling")
    tasks.append(telegram_task)
    
    # PyTalk bot needs to be started after its event handlers (in telegram_bot.main) are registered.
    # And it needs the main asyncio loop.
    # We connect to TeamTalk server and start its event processing here.
    pytalk_task = asyncio.create_task(start_pytalk_bot_internals(), name="PyTalkBotInternals")
    tasks.append(pytalk_task)


    flask_thread = None
    if core_config.FLASK_REGISTRATION_ENABLED:
        logger.info("Flask registration is enabled. Initializing Flask app.")
        # Flask needs the Aiogram bot instance for notifications and the current event loop for async tasks
        # Ensure global_aiogram_bot_instance is available (set by run_telegram_bot's AiogramBot init)
        # This is a bit fragile due to timing. A better approach might involve passing futures or explicit signals.
        await asyncio.sleep(0.1) # Short delay to allow aiogram_bot to be initialized by run_telegram_bot start
        
        if global_aiogram_bot_instance is None:
            logger.error("Aiogram bot instance not available for Flask app. Flask notifications might fail.")
            # Proceeding without it, or could exit.

        loop = asyncio.get_running_loop()
        flask_app = create_flask_app(global_aiogram_bot_instance, loop)
        
        # Run Flask in a separate daemon thread so it doesn't block asyncio
        flask_thread = threading.Thread(target=run_flask_app, args=(flask_app,), daemon=True, name="FlaskThread")
        flask_thread.start()
        logger.info(f"Flask app started in a separate thread. Accessible at http://{core_config.FLASK_HOST}:{core_config.FLASK_PORT}/register (or /web_registration/register if blueprint has prefix)")
    else:
        logger.info("Flask registration is disabled.")

    try:
        # Keep the main function alive while tasks are running
        # Or, more robustly, await the primary tasks.
        # If run_telegram_bot is blocking with start_polling, this gather might wait indefinitely for it.
        # start_polling itself is blocking.
        await asyncio.gather(*tasks, return_exceptions=True)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down...")
    except Exception as e:
        logger.exception(f"Unhandled exception in main execution: {e}")
    finally:
        logger.info("Performing cleanup...")
        
        # Gracefully stop Telegram polling (if not already stopped by its own exception handling)
        # This is tricky because start_polling is blocking. Cancellation might be needed.
        for task in tasks:
            if not task.done():
                task.cancel()
        
        # Wait for tasks to finish cancellation
        await asyncio.gather(*tasks, return_exceptions=True)

        # Shutdown PyTalk connections
        await shutdown_pytalk_bot()
        
        # Close database engine
        await close_db_engine()
        
        if flask_thread and flask_thread.is_alive():
            logger.info("Flask thread is still alive. It's a daemon, so it will exit with the main thread.")
            # Note: For graceful Flask shutdown, one might need to signal the Flask thread
            # or use a more sophisticated shutdown mechanism if Flask runs a production server like Gunicorn.
            # Werkzeug's dev server run in a thread will stop when the thread is killed or main exits.
            # The cleanup_flask_resources is called in run_flask_app's finally block.

        logger.info("Application shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user (Ctrl+C in asyncio.run).")
    except Exception as e:
        logger.critical(f"Critical error during asyncio.run: {e}", exc_info=True)
