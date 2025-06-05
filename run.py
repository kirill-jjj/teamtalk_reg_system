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

# Global task references
telegram_polling_task_ref: asyncio.Task | None = None
pytalk_task_ref: asyncio.Task | None = None
fastapi_server_task_ref: asyncio.Task | None = None


async def on_aiogram_shutdown_handler():
    """
    Handles graceful shutdown of related asyncio tasks when Aiogram is shutting down.
    This function is intended to be registered with Aiogram's dispatcher.
    """
    logger.info("Aiogram shutdown handler called. Cancelling related tasks...")

    tasks_to_cancel = [
        pytalk_task_ref,
        # telegram_polling_task_ref, # Aiogram handles its own polling task cancellation
        fastapi_server_task_ref
    ]

    for task in tasks_to_cancel:
        if task and not task.done():
            logger.info(f"Cancelling task: {task.get_name()}")
            task.cancel()
            try:
                await task # Allow task to process cancellation
            except asyncio.CancelledError:
                logger.info(f"Task {task.get_name()} was cancelled successfully.")
            except Exception as e:
                logger.error(f"Error during cancellation of task {task.get_name()}: {e}", exc_info=True)
        elif task and task.done():
            logger.info(f"Task {task.get_name()} is already done.")
        else:
            logger.debug(f"Task reference was None, skipping cancellation.")
    logger.info("Aiogram shutdown handler finished cancelling tasks.")


async def main():
    logger.info("Starting application...")

    global telegram_polling_task_ref, pytalk_task_ref, fastapi_server_task_ref

    actual_aiogram_bot_instance = None
    dp = None # Dispatcher

    try:
        # 1. Initialize Aiogram Bot and Dispatcher
        # The on_shutdown handler for the dispatcher will be set in telegram_bot.main
        actual_aiogram_bot_instance, dp = await run_telegram_bot(shutdown_handler_callback=on_aiogram_shutdown_handler)

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
        if dp and actual_aiogram_bot_instance:
            telegram_polling_task_ref = asyncio.create_task(
                start_telegram_polling(actual_aiogram_bot_instance, dp),
                name="TelegramBotPolling"
            )
        else:
            logger.error("Dispatcher or Bot not initialized. Telegram polling will not start.")

        pytalk_task_ref = asyncio.create_task(start_pytalk_bot_internals(), name="PyTalkBotInternals")
        
        fastapi_server_task_ref = asyncio.create_task(server.serve(), name="FastAPIServer")
        
        logger.info(f"FastAPI app starting on http{'s' if ssl_config else ''}://{core_config.WEB_APP_HOST}:{core_config.WEB_APP_PORT}")

        # --- Test Run Logic ---
        if "--test-run" in sys.argv:
            logger.info("Test run: Initializations complete or error occurred before this point. Exiting.")
            tasks_to_cancel_test_run = [
                telegram_polling_task_ref,
                pytalk_task_ref,
                fastapi_server_task_ref
            ]
            for task in tasks_to_cancel_test_run:
                if task and not task.done():
                    task.cancel()
            await asyncio.sleep(0.1) # Allow cancellations to register
            return # Exit main function early

        # Run all tasks concurrently
        # Only gather tasks that have been successfully created
        active_tasks_to_gather = [task for task in [telegram_polling_task_ref, pytalk_task_ref, fastapi_server_task_ref] if task is not None]
        if active_tasks_to_gather:
            await asyncio.gather(*active_tasks_to_gather, return_exceptions=True)
        else:
            logger.warning("No main tasks were started. Application might not be functional.")


    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down...")
    except asyncio.CancelledError:
        logger.info("Main task or one of its children was cancelled, shutting down...")
    except Exception as e:
        logger.exception(f"Unhandled exception in main execution: {e}")
    finally:
        logger.info("Performing cleanup in main finally block...")

        # Cancel tasks if they are still running
        # This section primarily handles cancellations not initiated by Aiogram's own shutdown.
        # If Aiogram's on_shutdown_handler was called, some tasks might already be cancelled.
        tasks_to_cancel_finally = [
            telegram_polling_task_ref, # Important if KeyboardInterrupt or other external signal stops main before Aiogram fully shuts down.
            pytalk_task_ref,
            fastapi_server_task_ref
        ]
        for task in tasks_to_cancel_finally:
            if task and not task.done():
                logger.info(f"Main finally: Cancelling task: {task.get_name()}")
                task.cancel()

        # Await the cancellation of all tasks
        tasks_to_await_finally = [task for task in [telegram_polling_task_ref, pytalk_task_ref, fastapi_server_task_ref] if task is not None]
        if tasks_to_await_finally:
            logger.info(f"Main finally: Awaiting {len(tasks_to_await_finally)} tasks...")
            # We use return_exceptions=True to ensure all tasks are awaited even if some were cancelled or failed.
            results = await asyncio.gather(*tasks_to_await_finally, return_exceptions=True)
            for i, result in enumerate(results):
                task_name = tasks_to_await_finally[i].get_name()
                if isinstance(result, asyncio.CancelledError):
                    logger.info(f"Main finally: Task {task_name} was cancelled.")
                elif isinstance(result, Exception):
                    logger.error(f"Main finally: Task {task_name} raised an exception: {result}", exc_info=result if not isinstance(result, asyncio.CancelledError) else False)
                else:
                    logger.info(f"Main finally: Task {task_name} completed with result: {result}")
        else:
            logger.info("Main finally: No tasks to await.")

        # Now, perform ordered shutdown of other resources
        logger.info("Main finally: Shutting down PyTalk bot...")
        await shutdown_pytalk_bot() # Should handle its own internal cleanup

        logger.info("Main finally: Closing database engine...")
        await close_db_engine()
        
        logger.info("Application shutdown sequence complete.")


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