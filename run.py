import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys

# --- Argument parsing for config file ---
# This is done before importing the settings module to ensure the environment
# variable is set before Pydantic-Settings tries to load the configuration.
parser = argparse.ArgumentParser(description="TeamTalk Registration System Bot")
parser.add_argument(
    "--config",
    type=str,
    default="config.toml",
    help="Path to the configuration TOML file.",
)
parser.add_argument(
    "--test-run",
    action="store_true",
    help="Run a quick test of startup and then exit.",
)
args = parser.parse_args()

if args.config:
    os.environ["CONFIG_FILE"] = args.config
    print(f"INFO: Using config file specified via --config: '{args.config}'")


from aiogram import Bot as AiogramBot
from aiogram import Dispatcher
import uvicorn

from bot.core.config import settings
from bot.core.db import close_db_engine, init_db
from bot.core.db.crud import (
    delete_telegram_registration_by_id,
    is_telegram_id_registered,
)
from bot.core.db.session import AsyncSessionLocal
from bot.core.tasks import periodic_database_cleanup
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


class Application:
    """Manages the lifecycle of the entire application, including Telegram bot,
    FastAPI server, TeamTalk connection, and background tasks.
    """

    def __init__(self, test_run: bool = False):
        self.test_run = test_run
        self.telegram_bot: AiogramBot | None = None
        self.dispatcher: Dispatcher | None = None
        self.fastapi_server: uvicorn.Server | None = None
        self.tasks: list[asyncio.Task] = []
        self.startup_event = asyncio.Event() # Event to signal successful startup

    async def _remove_admin_ids_from_registrations(self):
        """Checks for any admin IDs in the TelegramRegistration table on startup
        and removes them.
        """
        logger.info(
            "Performing startup check: Verifying admin IDs are not in TelegramRegistration table..."
        )

        if not settings.admin_ids:
            logger.info(
                "No ADMIN_IDS configured. Skipping startup check for admin registrations."
            )
            return

        removed_count = 0
        async with AsyncSessionLocal() as session:
            try:
                for admin_id in settings.admin_ids:
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
                    await session.commit()
                else:
                    logger.info(
                        "Startup check completed. No admin IDs found/removed from TelegramRegistration table."
                    )
            except Exception as e:
                logger.error(
                    f"Error during startup check for admin registrations: {e}",
                    exc_info=True,
                )
                await session.rollback()

    async def startup(self):
        logger.info("Starting application components...")

        # 1. Initialize Database
        await init_db()
        logger.info("Database initialized.")

        # 2. Run admin ID cleanup
        await self._remove_admin_ids_from_registrations()

        # 3. Initialize Telegram Bot
        self.telegram_bot, self.dispatcher = await run_telegram_bot()
        if self.telegram_bot:
            set_aiogram_bot_instance(self.telegram_bot)
            logger.info("Aiogram bot instance passed to TeamTalk connection module.")
            try:
                bot_info = await self.telegram_bot.get_me()
                self.telegram_bot.username = bot_info.username
                logger.info(
                    f"Telegram bot username '{bot_info.username}' cached successfully."
                )
            except Exception as e:
                logger.error(
                    f"Could not get Telegram bot info on startup. Deeplinks may not work. Error: {e}"
                )
                self.telegram_bot.username = None
        else:
            logger.warning("Aiogram bot instance was not available. Telegram polling will not start.")

        # 4. Start FastAPI server (if enabled)
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
            self.fastapi_server = uvicorn.Server(config=uvicorn_config)
            self.tasks.append(asyncio.create_task(self.fastapi_server.serve(), name="FastAPIServer"))
            logger.info(
                f"FastAPI app starting on http{'s' if ssl_config else ''}://{settings.web_app_host}:{settings.web_app_port}"
            )
        else:
            logger.info("WEB_REGISTRATION_ENABLED is false. FastAPI server will not be started.")

        # 5. Start TeamTalk Service
        self.tasks.append(
            asyncio.create_task(
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
        )

        # 6. Start Telegram Polling
        if self.telegram_bot and self.dispatcher:
            self.tasks.append(
                asyncio.create_task(
                    start_telegram_polling(self.telegram_bot, self.dispatcher),
                    name="TelegramBotPolling",
                )
            )
        else:
            logger.error("Telegram Bot or Dispatcher not initialized. Telegram polling will not start.")

        # 7. Start periodic database cleanup task
        self.tasks.append(
            asyncio.create_task(
                periodic_database_cleanup(), # No db_ready_event needed now
                name="DatabaseCleanupTask",
            )
        )
        logger.info("Periodic database cleanup task created.")

        self.startup_event.set() # Signal that all core components are started

    async def shutdown(self):
        logger.info("Shutting down application components...")

        # 1. Cancel all running tasks
        for task in self.tasks:
            if not task.done():
                logger.info(f"Cancelling task: {task.get_name()}")
                task.cancel()

        # Await tasks to allow them to handle cancellation
        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("All application tasks cancelled and awaited.")

        # 2. Close Aiogram dispatcher and bot session
        if self.dispatcher:
            await self.dispatcher.shutdown()
            logger.info("Aiogram dispatcher shut down.")
        if self.telegram_bot:
            await self.telegram_bot.session.close()
            logger.info("Aiogram bot session closed.")

        # 3. Close TeamTalk connection
        await close_teamtalk_connection()
        logger.info("PyTalk bot connection closed.")

        # 4. Close database engine
        await close_db_engine()
        logger.info("Database engine closed.")

        logger.info("Application shutdown complete.")

    async def run(self):
        try:
            await self.startup()
            if self.test_run:
                logger.info("Test run: Initializations complete. Exiting.")
                return

            # Keep the application running until interrupted
            await asyncio.gather(*self.tasks, return_exceptions=True)

        except asyncio.CancelledError:
            logger.info("Application run cancelled.")
        except Exception as e:
            logger.exception(f"Unhandled exception during application run: {e}")
        finally:
            await self.shutdown()


async def main():
    logger.info(f"Application starting with arguments: {sys.argv}")
    logger.info(f"NICK_NAME from config: {settings.nick_name}")

    app = Application(test_run=args.test_run)
    await app.run()


if __name__ == "__main__":
    if sys.platform != "win32":
        try:
            import uvloop
            uvloop.install()
            logger.info("uvloop installed as the asyncio event loop policy.")
        except ImportError:
            logger.warning("uvloop could not be imported. Using default asyncio event loop.")
        except Exception as e:
            logger.warning(f"Failed to install uvloop: {e}")
    else:
        logger.info("uvloop is not installed/used on Windows. Using default asyncio event loop.")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Application terminated by user (Ctrl+C).")
    except Exception as e:
        print(f"CRITICAL: Critical error during asyncio.run: {e}", file=sys.stderr)
