import asyncio
import sys # Added for --test-run
import logging # Added standard logging

import uvicorn # Added for FastAPI

from bot.fastapi_app.main import app as fastapi_app # Added FastAPI app instance
from bot.core import config as core_config
from bot.telegram_bot.main import run_telegram_bot, start_pytalk_bot_internals, start_telegram_polling
from bot.core.database import close_db_engine
from bot.core.teamtalk_client import shutdown_pytalk_bot
from pathlib import Path # For SSL path checking

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
# Set levels for other libraries
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("pytalk").setLevel(logging.INFO)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting application...")

    tasks = []
    actual_aiogram_bot_instance = None
    dp = None # Dispatcher

    try:
        # 1. Initialize Aiogram Bot and Dispatcher
        actual_aiogram_bot_instance, dp = await run_telegram_bot()
        
        # 2. Pass Bot instance to FastAPI app state
        if actual_aiogram_bot_instance:
            fastapi_app.state.aiogram_bot_instance = actual_aiogram_bot_instance
            logger.info("Aiogram Bot instance passed to FastAPI app state.")
        else:
            logger.error("Failed to initialize Aiogram Bot. FastAPI might not function correctly regarding bot interactions.")

        # 3. Configure Uvicorn server
        ssl_config = {}
        if core_config.WEB_APP_SSL_ENABLED: # Use new config name
            key_path = Path(core_config.WEB_APP_SSL_KEY_PATH) # Use new config name
            cert_path = Path(core_config.WEB_APP_SSL_CERT_PATH) # Use new config name
            if key_path.exists() and cert_path.exists():
                ssl_config["ssl_keyfile"] = str(key_path)
                ssl_config["ssl_certfile"] = str(cert_path)
                logger.info(f"SSL enabled for FastAPI. Key: {key_path}, Cert: {cert_path}")
            else:
                logger.warning(f"SSL enabled in config, but key/cert files not found. Key: {key_path}, Cert: {cert_path}. FastAPI will run without SSL.")
        
        uvicorn_config = uvicorn.Config(
            app=fastapi_app,
            host=core_config.WEB_APP_HOST, # Use new config name
            port=core_config.WEB_APP_PORT, # Use new config name
            loop="asyncio",
            log_level="info", # You can adjust uvicorn's log level
            forwarded_allow_ips=core_config.WEB_APP_FORWARDED_ALLOW_IPS,
            proxy_headers=core_config.WEB_APP_PROXY_HEADERS,
            **ssl_config
        )
        server = uvicorn.Server(config=uvicorn_config)

        # 4. Define tasks to run concurrently
        # Telegram polling task
        if dp and actual_aiogram_bot_instance:
             telegram_polling_task = asyncio.create_task(
                start_telegram_polling(actual_aiogram_bot_instance, dp), 
                name="TelegramBotPolling"
            )
             tasks.append(telegram_polling_task)
        else:
            logger.error("Dispatcher or Bot not initialized. Telegram polling will not start.")

        pytalk_task = asyncio.create_task(start_pytalk_bot_internals(), name="PyTalkBotInternals")
        tasks.append(pytalk_task)
        
        # FastAPI server task
        fastapi_server_task = asyncio.create_task(server.serve(), name="FastAPIServer")
        tasks.append(fastapi_server_task)
        
        logger.info(f"FastAPI app starting on http{'s' if ssl_config else ''}://{core_config.WEB_APP_HOST}:{core_config.WEB_APP_PORT}") # Use new config names

        # --- Test Run Logic ---
        if "--test-run" in sys.argv:
            logger.info("Test run: Initializations complete or error occurred before this point. Exiting.")
            # The Uvicorn server task (fastapi_server_task) was created but not awaited directly here,
            # it's part of asyncio.gather. For a test run, we don't want to run indefinitely.
            # We can cancel the tasks created for a cleaner exit, though return will also work.
            for task in tasks:
                task.cancel()
            # A brief moment to allow cancellations to register if needed, then exit.
            await asyncio.sleep(0.1) 
            return # Exit main function early

        # Run all tasks concurrently
        await asyncio.gather(*tasks, return_exceptions=True)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down...")
    except asyncio.CancelledError:
        logger.info("One or more tasks were cancelled, shutting down...")
    except Exception as e:
        logger.exception(f"Unhandled exception in main execution: {e}")
    finally:
        logger.info("Performing cleanup...")
        
        # Отмена задач, если они еще не завершены
        for task in tasks:
            if not task.done():
                task.cancel()
        
        # Ожидание завершения отмены задач
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        await shutdown_pytalk_bot()
        await close_db_engine()
        
        logger.info("Application shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Using print here as logger might not be available or configured if asyncio.run(main()) fails very early
        print("Application terminated by user (Ctrl+C in asyncio.run).") 
    except Exception as e:
        # Using print for critical errors during asyncio.run if logger itself might be part of the problem
        print(f"CRITICAL: Critical error during asyncio.run: {e}", file=sys.stderr)
        # Optionally, try to log with a fallback basic logger if the main one failed or wasn't set up
        # logging.basicConfig(level=logging.CRITICAL, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        # logging.getLogger("run_critical").critical(f"Critical error during asyncio.run: {e}", exc_info=True)
        # For this task, direct print to stderr is simplest for bootstrap errors.