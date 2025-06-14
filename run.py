import sys # Must be one of the first
import os # For os.path.exists, needed early
from typing import Optional # For type hinting if used in moved function

# Attempt to load python-dotenv. If not available, loading .env files will silently fail
# or could raise an error if not handled. For this controlled environment, assume it's installed.
try:
    from dotenv import load_dotenv, find_dotenv
except ImportError:
    # This function will be a no-op if python-dotenv is not installed.
    print("[bootstrap_warning] python-dotenv module not found. .env file loading will be skipped.")
    def load_dotenv(*args, **kwargs): pass
    def find_dotenv(*args, **kwargs): return None

# --- Early .env file loading logic ---
# This logic is moved here to run before any other module (especially bot.core.config)
# reads environment variables.
def _early_load_env_file(env_path: Optional[str] = None) -> None:
    """
    Loads environment variables from a .env file.
    Uses print for feedback as logging might not be configured this early.
    """
    value_to_print = env_path if env_path else "<default>"
    print(f"[_early_load_env_file] Attempting to load .env file. Provided path: '{value_to_print}'")
    if env_path and os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
        print(f"[_early_load_env_file] SUCCESS: Loaded .env file from specified path: {env_path}")
    else:
        if env_path:
            print(f"[_early_load_env_file] INFO: Specified .env file path not found: {env_path}. Trying default locations.")

        # Attempt to find .env only if no specific path was given or if it wasn't found
        # This behavior matches the original intent of find_dotenv() being a fallback.
        # If a path is given and not found, some might argue it shouldn't fall back.
        # For now, maintaining original logic: fallback if specified path not found.
        dotenv_path_found = find_dotenv(usecwd=True) # usecwd=True to search in current dir first

        if dotenv_path_found and os.path.exists(dotenv_path_found):
            load_dotenv(dotenv_path_found)
            print(f"[_early_load_env_file] SUCCESS: Loaded .env file from default location: {dotenv_path_found}")
        elif not env_path : # Only print "could not find" if no specific path was ever tried or default search failed
            print(f"[_early_load_env_file] INFO: Could not find .env file in default locations.")
        # If env_path was specified but not found, and default also not found, the earlier message about specified path is key.

# Process command line arguments for .env file path BEFORE other imports that might rely on os.environ
_env_file_to_load = None
if len(sys.argv) > 1:
    # Simplified logic: if --test-run is first, potential .env is second. Otherwise, .env is first.
    if sys.argv[1] == "--test-run":
        if len(sys.argv) > 2:
            _env_file_to_load = sys.argv[2]
    else: # First argument is not --test-run, so assume it's an env file path
        _env_file_to_load = sys.argv[1]
_early_load_env_file(_env_file_to_load)
# --- End of early .env file loading ---

import asyncio
import logging

import uvicorn

# Now that .env is loaded (or attempted), these imports can proceed and config will see the right values
from bot.fastapi_app.main import app as fastapi_app
from bot.teamtalk.connection import launch_teamtalk_service
from bot.teamtalk import events as _ # To register core TT event handlers
from bot.core import config as core_config # This should now see env vars from custom .env
from bot.telegram_bot.main import run_telegram_bot, start_telegram_polling
from bot.core.db import close_db_engine
from bot.teamtalk.connection import close_teamtalk_connection
from pathlib import Path

# Configure logging AFTER .env load, as .env might contain logging settings in a real app
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
# Set levels for other libraries
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("pytalk").setLevel(logging.INFO)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)
# Logger for run.py itself
logger = logging.getLogger(__name__)

# --- Imports for Admin ID Check ---
from bot.core.db.crud import is_telegram_id_registered, delete_telegram_registration_by_id
from bot.core.db.session import AsyncSessionLocal
# --- End Imports for Admin ID Check ---

# Global task references
telegram_polling_task_ref: asyncio.Task | None = None
pytalk_task_ref: asyncio.Task | None = None
fastapi_server_task_ref: asyncio.Task | None = None
db_cleanup_task_ref: asyncio.Task | None = None
admin_check_task_ref: asyncio.Task | None = None


async def remove_admin_ids_from_registrations(db_ready_event: asyncio.Event):
    '''
    Checks for any admin IDs in the TelegramRegistration table on startup
    and removes them.
    '''
    await db_ready_event.wait() # Ensure DB is ready
    logger.info("Performing startup check: Verifying admin IDs are not in TelegramRegistration table...")

    if not core_config.ADMIN_IDS:
        logger.info("No ADMIN_IDS configured. Skipping startup check for admin registrations.")
        return

    removed_count = 0
    # Use the session factory as a context manager
    async with AsyncSessionLocal() as session:
        try:
            for admin_id_str in core_config.ADMIN_IDS: # ADMIN_IDS are strings from config
                admin_id = int(admin_id_str) # Convert to int for DB operations
                if await is_telegram_id_registered(session, admin_id):
                    logger.info(f"Admin ID {admin_id} found in TelegramRegistration table. Attempting removal.")
                    deleted = await delete_telegram_registration_by_id(session, admin_id)
                    if deleted:
                        logger.info(f"Admin ID {admin_id} successfully removed from TelegramRegistration table.")
                        removed_count += 1
                    else:
                        logger.warning(f"Admin ID {admin_id} was reported as registered, but removal failed or found no rows to delete.")

            if removed_count > 0:
                logger.info(f"Startup check completed. Removed {removed_count} admin ID(s) from TelegramRegistration table.")
                await session.commit() # Commit changes if any deletions were made
            else:
                logger.info("Startup check completed. No admin IDs found/removed from TelegramRegistration table.")
        except Exception as e:
            logger.error(f"Error during startup check for admin registrations: {e}", exc_info=True)
            await session.rollback() # Rollback on any error during the process


async def on_aiogram_shutdown_handler():
    """
    Handles graceful shutdown of related asyncio tasks when Aiogram is shutting down.
    This function is intended to be registered with Aiogram's dispatcher.
    """
    logger.info("Aiogram shutdown handler called. Cancelling related tasks...")

    tasks_to_cancel = [
        pytalk_task_ref,
        # telegram_polling_task_ref, # Aiogram handles its own polling task cancellation
        fastapi_server_task_ref,
        db_cleanup_task_ref,
        admin_check_task_ref
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

    global telegram_polling_task_ref, pytalk_task_ref, fastapi_server_task_ref, db_cleanup_task_ref, admin_check_task_ref
    from bot.core.tasks import periodic_database_cleanup

    actual_aiogram_bot_instance = None
    dp = None # Dispatcher
    db_initialized_event = asyncio.Event()

    try:
        # 1. Initialize Aiogram Bot and Dispatcher
        # The on_shutdown handler for the dispatcher will be set in telegram_bot.main
        actual_aiogram_bot_instance, dp = await run_telegram_bot(
            shutdown_handler_callback=on_aiogram_shutdown_handler,
            db_ready_event=db_initialized_event
        )

        # 2. Pass Bot instance to FastAPI app state

        # 3. Configure Uvicorn server (conditionally)
        if core_config.WEB_REGISTRATION_ENABLED:
            ssl_config = {}
            if core_config.WEB_APP_SSL_ENABLED:
                key_path = Path(core_config.WEB_APP_SSL_KEY_PATH)
                cert_path = Path(core_config.WEB_APP_SSL_CERT_PATH)
                if key_path.exists() and cert_path.exists():
                    ssl_config["ssl_keyfile"] = str(key_path)
                    ssl_config["ssl_certfile"] = str(cert_path)
                    logger.info(f"SSL enabled for FastAPI. Key: {key_path}, Cert: {cert_path}")
                else:
                    logger.warning(f"SSL enabled in config, but key/cert files not found. Key: {key_path}, Cert: {cert_path}. FastAPI will run without SSL.")

            uvicorn_config = uvicorn.Config(
                app=fastapi_app,
                host=core_config.WEB_APP_HOST,
                port=core_config.WEB_APP_PORT,
                loop="asyncio",
                log_level="info",
                forwarded_allow_ips=core_config.WEB_APP_FORWARDED_ALLOW_IPS,
                proxy_headers=core_config.WEB_APP_PROXY_HEADERS,
                **ssl_config
            )
            server = uvicorn.Server(config=uvicorn_config)

            fastapi_server_task_ref = asyncio.create_task(server.serve(), name="FastAPIServer")

            logger.info(f"FastAPI app starting on http{'s' if ssl_config else ''}://{core_config.WEB_APP_HOST}:{core_config.WEB_APP_PORT}")
        else:
            logger.info("WEB_REGISTRATION_ENABLED is false in config. FastAPI server (web registration) will not be started.")
            # fastapi_server_task_ref remains None (its initial value at the top of main())

        # 4. Define tasks to run concurrently
        if dp and actual_aiogram_bot_instance:
            telegram_polling_task_ref = asyncio.create_task(
                start_telegram_polling(actual_aiogram_bot_instance, dp),
                name="TelegramBotPolling"
            )
        else:
            logger.error("Dispatcher or Bot not initialized. Telegram polling will not start.")

        pytalk_task_ref = asyncio.create_task(
            launch_teamtalk_service(
                host_name=core_config.HOST_NAME,
                tcp_port=core_config.TCP_PORT,
                udp_port=core_config.UDP_PORT,
                user_name=core_config.USER_NAME,
                password=core_config.PASSWORD,
                nickname=core_config.NICK_NAME,
                encrypted=core_config.ENCRYPTED,
                join_channel_path=core_config.TEAMTALK_JOIN_CHANNEL,
                join_channel_pass=core_config.TEAMTALK_JOIN_CHANNEL_PASSWORD,
                bot_gender=core_config.TEAMTALK_GENDER,
                bot_status_text=core_config.TEAMTALK_STATUS_TEXT
            ),
            name="PyTalkBotInternals"
        )
        
        # fastapi_server_task_ref is now set conditionally above
        

        # 5. Create and start the periodic database cleanup task
        db_cleanup_task_ref = asyncio.create_task(
            periodic_database_cleanup(db_ready_event=db_initialized_event),
            name="DatabaseCleanupTask"
        )
        logger.info("Periodic database cleanup task created.")

        # 6. Create and start the admin ID registration check task
        admin_check_task_ref = asyncio.create_task(
            remove_admin_ids_from_registrations(db_ready_event=db_initialized_event),
            name="AdminRegistrationCheckTask"
        )
        logger.info("Admin ID registration check task created.")

        # --- Test Run Logic ---
        if "--test-run" in sys.argv:
            logger.info("Test run: Initializations complete or error occurred before this point. Exiting.")
            tasks_to_cancel_test_run = [
                telegram_polling_task_ref,
                pytalk_task_ref,
                fastapi_server_task_ref,
                db_cleanup_task_ref,
                admin_check_task_ref
            ]
            for task in tasks_to_cancel_test_run:
                if task and not task.done():
                    task.cancel()
            await asyncio.sleep(0.1) # Allow cancellations to register
            return # Exit main function early

        # Run all tasks concurrently
        # Only gather tasks that have been successfully created
        active_tasks_to_gather = [task for task in [telegram_polling_task_ref, pytalk_task_ref, fastapi_server_task_ref, db_cleanup_task_ref, admin_check_task_ref] if task is not None]
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
            fastapi_server_task_ref,
            db_cleanup_task_ref,
            admin_check_task_ref
        ]
        for task in tasks_to_cancel_finally:
            if task and not task.done():
                logger.info(f"Main finally: Cancelling task: {task.get_name()}")
                task.cancel()

        # Await the cancellation of all tasks
        tasks_to_await_finally = [task for task in [telegram_polling_task_ref, pytalk_task_ref, fastapi_server_task_ref, db_cleanup_task_ref, admin_check_task_ref] if task is not None]
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
        await close_teamtalk_connection() # Should handle its own internal cleanup

        logger.info("Main finally: Closing database engine...")
        await close_db_engine()
        
        logger.info("Application shutdown sequence complete.")


if __name__ == "__main__":
    # The .env loading logic has been moved to the top of the file,
    # before other imports and logging configuration.
    # The sys.argv parsing for --test-run for exiting early is still in main().
    logger.info(f"Application starting with arguments: {sys.argv}")
    logger.info(f"NICK_NAME from config: {core_config.NICK_NAME}")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Using print here as logger might not be available or configured if asyncio.run(main()) fails very early
        print("Application terminated by user (Ctrl+C in asyncio.run).")
    except Exception as e:
        # Using print for critical errors during asyncio.run if logger itself might be part of the problem
        print(f"CRITICAL: Critical error during asyncio.run: {e}", file=sys.stderr)