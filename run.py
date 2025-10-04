import asyncio
import logging
import os
from pathlib import Path
import sys

# --- Argument parsing for config file ---
# This is done before importing the settings module to ensure the environment
# variable is set before Pydantic-Settings tries to load the configuration.
if "--config" in sys.argv:
    try:
        config_file_index = sys.argv.index("--config") + 1
        config_file = sys.argv[config_file_index]
        os.environ["CONFIG_FILE"] = config_file
        # Use a print statement here as logger is not configured yet
        print(f"INFO: Using config file specified via --config: '{config_file}'")
    except (ValueError, IndexError):
        print("ERROR: --config flag must be followed by a file path.", file=sys.stderr)
        sys.exit(1)


import uvicorn

from bot.core.config import settings
from bot.core.db import close_db_engine
from bot.core.db.crud import (
    delete_telegram_registration_by_id,
    is_telegram_id_registered,
)
from bot.core.db.session import AsyncSessionLocal
from bot.fastapi_app.main import app as fastapi_app
from bot.teamtalk.connection import (
    close_teamtalk_connection,
    launch_teamtalk_service,
    set_aiogram_bot_instance,
)
from bot.telegram_bot.main import run_telegram_bot, start_telegram_polling

# Configure logging AFTER .env load, as .env might contain logging settings in a real app
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Set levels for other libraries
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("pytalk").setLevel(logging.INFO)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)
# Logger for run.py itself
logger = logging.getLogger(__name__)

# --- Imports for Admin ID Check ---
# --- End Imports for Admin ID Check ---

# Global task references
telegram_polling_task_ref: asyncio.Task | None = None
pytalk_task_ref: asyncio.Task | None = None
fastapi_server_task_ref: asyncio.Task | None = None
db_cleanup_task_ref: asyncio.Task | None = None
admin_check_task_ref: asyncio.Task | None = None


async def remove_admin_ids_from_registrations(db_ready_event: asyncio.Event):
    """Checks for any admin IDs in the TelegramRegistration table on startup
    and removes them.
    """
    await db_ready_event.wait()  # Ensure DB is ready
    logger.info(
        "Performing startup check: Verifying admin IDs are not in TelegramRegistration table..."
    )

    if not settings.admin_ids:
        logger.info(
            "No ADMIN_IDS configured. Skipping startup check for admin registrations."
        )
        return

    removed_count = 0
    # Use the session factory as a context manager
    async with AsyncSessionLocal() as session:
        try:
            for admin_id in settings.admin_ids:  # ADMIN_IDS are strings from config
                if await is_telegram_id_registered(session, admin_id):
                    logger.info(
                        f"Admin ID {admin_id} found in TelegramRegistration table. Attempting removal."
                    )
                    deleted = await delete_telegram_registration_by_id(
                        session, admin_id
                    )
                    if deleted:
                        logger.info(
                            f"Admin ID {admin_id} successfully removed from TelegramRegistration table."
                        )
                        removed_count += 1
                    else:
                        logger.warning(
                            f"Admin ID {admin_id} was reported as registered, but removal failed or found no rows to delete."
                        )

            if removed_count > 0:
                logger.info(
                    f"Startup check completed. Removed {removed_count} admin ID(s) from TelegramRegistration table."
                )
                await session.commit()  # Commit changes if any deletions were made
            else:
                logger.info(
                    "Startup check completed. No admin IDs found/removed from TelegramRegistration table."
                )
        except Exception as e:
            logger.error(
                f"Error during startup check for admin registrations: {e}",
                exc_info=True,
            )
            await session.rollback()  # Rollback on any error during the process


async def on_aiogram_shutdown_handler():
    """Handles graceful shutdown of related asyncio tasks when Aiogram is shutting down.
    This function is intended to be registered with Aiogram's dispatcher.
    """
    logger.info("Aiogram shutdown handler called. Cancelling related tasks...")

    tasks_to_cancel = [
        pytalk_task_ref,
        # telegram_polling_task_ref, # Aiogram handles its own polling task cancellation
        fastapi_server_task_ref,
        db_cleanup_task_ref,
        admin_check_task_ref,
    ]

    for task in tasks_to_cancel:
        if task and not task.done():
            logger.info(f"Cancelling task: {task.get_name()}")
            task.cancel()
            try:
                await task  # Allow task to process cancellation
            except asyncio.CancelledError:
                logger.info(f"Task {task.get_name()} was cancelled successfully.")
            except Exception as e:
                logger.error(
                    f"Error during cancellation of task {task.get_name()}: {e}",
                    exc_info=True,
                )
        elif task and task.done():
            logger.info(f"Task {task.get_name()} is already done.")
        else:
            logger.debug("Task reference was None, skipping cancellation.")
    logger.info("Aiogram shutdown handler finished cancelling tasks.")


async def main():
    logger.info("Starting application...")

    global telegram_polling_task_ref, pytalk_task_ref, fastapi_server_task_ref, db_cleanup_task_ref, admin_check_task_ref
    from bot.core.tasks import periodic_database_cleanup

    actual_aiogram_bot_instance = None
    dp = None  # Dispatcher
    db_initialized_event = asyncio.Event()

    try:
        # 1. Initialize Aiogram Bot and Dispatcher
        # The on_shutdown handler for the dispatcher will be set in telegram_bot.main
        actual_aiogram_bot_instance, dp = await run_telegram_bot(
            shutdown_handler_callback=on_aiogram_shutdown_handler,
            db_ready_event=db_initialized_event,
        )

        # Set the Aiogram bot instance for TeamTalk bot to use
        if actual_aiogram_bot_instance:
            set_aiogram_bot_instance(actual_aiogram_bot_instance)
            logger.info("Aiogram bot instance passed to TeamTalk connection module.")

            try:
                bot_info = await actual_aiogram_bot_instance.get_me()
                actual_aiogram_bot_instance.username = bot_info.username
                logger.info(
                    f"Telegram bot username '{bot_info.username}' cached successfully."
                )
            except Exception as e:
                logger.error(
                    f"Could not get Telegram bot info on startup. Deeplinks may not work. Error: {e}"
                )
                actual_aiogram_bot_instance.username = None

        else:
            logger.warning(
                "Aiogram bot instance was not available after run_telegram_bot. Cannot set on pytalk_bot."
            )

        # 2. Pass Bot instance to FastAPI app state

        # 3. Configure Uvicorn server (conditionally)
        if settings.web_registration_enabled:
            ssl_config = {}
            if settings.web_app_ssl_enabled:
                key_path = Path(settings.web_app_ssl_key_path)
                cert_path = Path(settings.web_app_ssl_cert_path)
                if key_path.exists() and cert_path.exists():
                    ssl_config["ssl_keyfile"] = str(key_path)
                    ssl_config["ssl_certfile"] = str(cert_path)
                    logger.info(f"SSL enabled for FastAPI. Key: {key_path}, Cert: {cert_path}")
                else:
                    logger.warning(
                        f"SSL enabled in config, but key/cert files not found. Key: {key_path}, Cert: {cert_path}. FastAPI will run without SSL."
                    )

            uvicorn_config = uvicorn.Config(
                app=fastapi_app,
                host=settings.web_app_host,
                port=settings.web_app_port,
                loop="asyncio",
                log_level="info",
                forwarded_allow_ips=settings.web_app_forwarded_allow_ips,
                proxy_headers=settings.web_app_proxy_headers,
                **ssl_config,
            )
            server = uvicorn.Server(config=uvicorn_config)

            fastapi_server_task_ref = asyncio.create_task(
                server.serve(), name="FastAPIServer"
            )

            logger.info(
                f"FastAPI app starting on http{'s' if ssl_config else ''}://{settings.web_app_host}:{settings.web_app_port}"
            )
        else:
            logger.info(
                "WEB_REGISTRATION_ENABLED is false in config. FastAPI server (web registration) will not be started."
            )
            # fastapi_server_task_ref remains None (its initial value at the top of main())

        # 4. Define tasks to run concurrently
        if dp and actual_aiogram_bot_instance:
            telegram_polling_task_ref = asyncio.create_task(
                start_telegram_polling(actual_aiogram_bot_instance, dp),
                name="TelegramBotPolling",
            )
        else:
            logger.error(
                "Dispatcher or Bot not initialized. Telegram polling will not start."
            )

        pytalk_task_ref = asyncio.create_task(
            launch_teamtalk_service(
                host_name=settings.host_name,
                tcp_port=settings.port,
                udp_port=settings.udp_port,
                user_name=settings.user_name,
                password=settings.password,
                nickname=settings.nick_name,
                encrypted=settings.encrypted,
                join_channel_path=settings.tt_join_channel,
                join_channel_pass=settings.tt_join_channel_password,
                bot_gender=settings.tt_gender,
                bot_status_text=settings.tt_status_text,
            ),
            name="PyTalkBotInternals",
        )

        # fastapi_server_task_ref is now set conditionally above

        # 5. Create and start the periodic database cleanup task
        db_cleanup_task_ref = asyncio.create_task(
            periodic_database_cleanup(db_ready_event=db_initialized_event),
            name="DatabaseCleanupTask",
        )
        logger.info("Periodic database cleanup task created.")

        # 6. Create and start the admin ID registration check task
        admin_check_task_ref = asyncio.create_task(
            remove_admin_ids_from_registrations(db_ready_event=db_initialized_event),
            name="AdminRegistrationCheckTask",
        )
        logger.info("Admin ID registration check task created.")

        # --- Test Run Logic ---
        if "--test-run" in sys.argv:
            logger.info(
                "Test run: Initializations complete or error occurred before this point. Exiting."
            )
            tasks_to_cancel_test_run = [
                telegram_polling_task_ref,
                pytalk_task_ref,
                fastapi_server_task_ref,
                db_cleanup_task_ref,
                admin_check_task_ref,
            ]
            for task in tasks_to_cancel_test_run:
                if task and not task.done():
                    task.cancel()
            await asyncio.sleep(0.1)  # Allow cancellations to register
            return  # Exit main function early

        # Run all tasks concurrently
        # Only gather tasks that have been successfully created
        active_tasks_to_gather = [
            task
            for task in [
                telegram_polling_task_ref,
                pytalk_task_ref,
                fastapi_server_task_ref,
                db_cleanup_task_ref,
                admin_check_task_ref,
            ]
            if task is not None
        ]
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
            telegram_polling_task_ref,  # Important if KeyboardInterrupt or other external signal stops main before Aiogram fully shuts down.
            pytalk_task_ref,
            fastapi_server_task_ref,
            db_cleanup_task_ref,
            admin_check_task_ref,
        ]
        for task in tasks_to_cancel_finally:
            if task and not task.done():
                logger.info(f"Main finally: Cancelling task: {task.get_name()}")
                task.cancel()

        # Await the cancellation of all tasks
        tasks_to_await_finally = [
            task
            for task in [
                telegram_polling_task_ref,
                pytalk_task_ref,
                fastapi_server_task_ref,
                db_cleanup_task_ref,
                admin_check_task_ref,
            ]
            if task is not None
        ]
        if tasks_to_await_finally:
            logger.info(f"Main finally: Awaiting {len(tasks_to_await_finally)} tasks...")
            # We use return_exceptions=True to ensure all tasks are awaited even if some were cancelled or failed.
            results = await asyncio.gather(
                *tasks_to_await_finally, return_exceptions=True
            )
            for i, result in enumerate(results):
                task_name = tasks_to_await_finally[i].get_name()
                if isinstance(result, asyncio.CancelledError):
                    logger.info(f"Main finally: Task {task_name} was cancelled.")
                elif isinstance(result, Exception):
                    logger.error(
                        f"Main finally: Task {task_name} raised an exception: {result}",
                        exc_info=result
                        if not isinstance(result, asyncio.CancelledError)
                        else False,
                    )
                else:
                    logger.info(
                        f"Main finally: Task {task_name} completed with result: {result}"
                    )
        else:
            logger.info("Main finally: No tasks to await.")

        # Now, perform ordered shutdown of other resources
        logger.info("Main finally: Shutting down PyTalk bot...")
        await close_teamtalk_connection()  # Should handle its own internal cleanup

        logger.info("Main finally: Closing database engine...")
        await close_db_engine()

        logger.info("Application shutdown sequence complete.")


if __name__ == "__main__":
    # The .env loading logic has been moved to the top of the file,
    # before other imports and logging configuration.
    # The sys.argv parsing for --test-run for exiting early is still in main().
    logger.info(f"Application starting with arguments: {sys.argv}")
    logger.info(f"NICK_NAME from config: {settings.nick_name}")
    try:
        # Before asyncio.run(main())
        if sys.platform != "win32":  # Check if not Windows
            try:
                import uvloop

                uvloop.install()
                logger.info("uvloop installed as the asyncio event loop policy.")
            except ImportError:
                # This case might occur if, for some reason, uvloop wasn't installed despite non-Windows platform.
                logger.warning(
                    "uvloop could not be imported, even on a non-Windows platform. Using default asyncio event loop."
                )
            except Exception as e:
                logger.warning(
                    f"Failed to install uvloop (though import was successful), falling back to default asyncio event loop: {e}"
                )
        else:
            # This message clarifies why uvloop is not being used on Windows.
            logger.info(
                "uvloop is not installed/used on Windows (due to environment markers). Using default asyncio event loop."
            )
        asyncio.run(main())
    except KeyboardInterrupt:
        # Using print here as logger might not be available or configured if asyncio.run(main()) fails very early
        print("Application terminated by user (Ctrl+C in asyncio.run).")
    except Exception as e:
        # Using print for critical errors during asyncio.run if logger itself might be part of the problem
        print(f"CRITICAL: Critical error during asyncio.run: {e}", file=sys.stderr)
