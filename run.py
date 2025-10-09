"""This module is the main entry point for the application."""
import argparse
import asyncio
import functools
import logging
import os
from pathlib import Path
import sys

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher
import pytalk
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
)
from bot.teamtalk.events import (
    on_error,
    on_message,
    on_my_connect,
    on_my_connection_lost,
    on_my_disconnect,
    on_my_kicked_from_channel,
    on_my_login,
    on_ready,
    on_user_account_new,
    on_user_account_remove,
)
from bot.telegram_bot.main import run_telegram_bot

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

# Configure logging AFTER .env load, as .env might contain logging settings.
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
    """Manages the application lifecycle.

    This includes the Telegram bot, FastAPI server, TeamTalk connection,
    and background tasks.
    """

    def __init__(self, *, test_run: bool = False) -> None:
        """Initializes the application."""
        self.test_run = test_run
        self.telegram_bot: AiogramBot | None = None
        self.dispatcher: Dispatcher | None = None
        self.fastapi_server: uvicorn.Server | None = None
        self.pytalk_bot: pytalk.TeamTalkBot | None = None # New: pytalk bot instance
        self.tasks: list[asyncio.Task] = []
        self.startup_event = asyncio.Event() # Event to signal successful startup

    async def _remove_admin_ids_from_registrations(self) -> None:
        """Checks for and removes admin IDs from the registration table on startup."""
        logger.info(
            "Performing startup check: Verifying admin IDs are not in "
            "TelegramRegistration table..."
        )

        if not settings.admin_ids:
            logger.info(
                "No ADMIN_IDS configured. Skipping startup check for admin "
                "registrations."
            )
            return

        removed_count = 0
        async with AsyncSessionLocal() as session:
            try:
                for admin_id in settings.admin_ids:
                    if await is_telegram_id_registered(session, admin_id):
                        logger.info(
                            "Admin ID %s found in TelegramRegistration table. "
                            "Attempting removal.",
                            admin_id,
                        )
                        deleted = await delete_telegram_registration_by_id(
                            session, admin_id
                        )
                        if deleted:
                            logger.info(
                                "Admin ID %s successfully removed from "
                                "TelegramRegistration table.",
                                admin_id,
                            )
                            removed_count += 1
                        else:
                            logger.warning(
                                "Admin ID %s was reported as registered, but "
                                "removal failed or found no rows to delete.",
                                admin_id,
                            )

                if removed_count > 0:
                    logger.info(
                        "Startup check completed. Removed %s admin ID(s) from "
                        "TelegramRegistration table.",
                        removed_count,
                    )
                    await session.commit()
                else:
                    logger.info(
                        "Startup check completed. No admin IDs found/removed "
                        "from TelegramRegistration table."
                    )
            except Exception:
                logger.exception(
                    "Error during startup check for admin registrations:"
                )
                await session.rollback()

    async def _init_pytalk_bot(self) -> None:
        self.pytalk_bot = pytalk.TeamTalkBot(client_name=settings.client_name)
        logger.info("PyTalk bot instance created.")

        # Register PyTalk event handlers
        self.pytalk_bot.on_ready = functools.partial(on_ready, self.pytalk_bot)
        self.pytalk_bot.on_my_login = functools.partial(
            on_my_login, self.pytalk_bot
        )
        self.pytalk_bot.on_message = functools.partial(on_message, self.pytalk_bot)
        self.pytalk_bot.on_error = functools.partial(on_error, self.pytalk_bot)
        self.pytalk_bot.on_my_connect = functools.partial(
            on_my_connect, self.pytalk_bot
        )
        self.pytalk_bot.on_my_disconnect = functools.partial(
            on_my_disconnect, self.pytalk_bot
        )
        self.pytalk_bot.on_my_connection_lost = functools.partial(
            on_my_connection_lost, self.pytalk_bot
        )
        self.pytalk_bot.on_my_kicked_from_channel = functools.partial(
            on_my_kicked_from_channel, self.pytalk_bot
        )
        self.pytalk_bot.on_user_account_new = functools.partial(
            on_user_account_new, self.pytalk_bot
        )
        self.pytalk_bot.on_user_account_remove = functools.partial(
            on_user_account_remove, self.pytalk_bot
        )
        logger.info("PyTalk event handlers registered.")

    async def _init_telegram_bot(self) -> None:
        # Now pass self (the Application instance) to run_telegram_bot
        self.telegram_bot, self.dispatcher = await run_telegram_bot(
            self.pytalk_bot, self
        )
        if self.telegram_bot:
            # Pass the Aiogram bot instance to the pytalk_bot
            self.pytalk_bot.aiogram_bot_ref = self.telegram_bot
            logger.info("Aiogram bot instance passed to PyTalk bot.")
            try:
                bot_info = await self.telegram_bot.get_me()
                self.telegram_bot.username = bot_info.username
                logger.info(
                    "Telegram bot username '%s' cached successfully.",
                    bot_info.username,
                )
            except Exception:
                logger.exception(
                    "Could not get Telegram bot info on startup. "
                    "Deeplinks may not work."
                )
                self.telegram_bot.username = None
        else:
            logger.warning(
                "Aiogram bot instance was not available. "
                "Telegram polling will not start."
            )

    async def _start_fastapi_server(self) -> None:
        if settings.web_registration_enabled:
            ssl_config = {}
            if settings.web_app_ssl_enabled:
                key_path = Path(settings.web_app_ssl_key_path)
                cert_path = Path(settings.web_app_ssl_cert_path)
                if key_path.exists() and cert_path.exists():
                    ssl_config["ssl_keyfile"] = str(key_path)
                    ssl_config["ssl_certfile"] = str(cert_path)
                    logger.info(
                        "SSL enabled for FastAPI. Key: %s, Cert: %s",
                        key_path,
                        cert_path,
                    )
                else:
                    logger.warning(
                        "SSL enabled in config, but key/cert files not found. "
                        "Key: %s, Cert: %s. FastAPI will run without SSL.",
                        key_path,
                        cert_path,
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
            self.tasks.append(
                asyncio.create_task(
                    self.fastapi_server.serve(), name="FastAPIServer"
                )
            )
            logger.info(
                "FastAPI app starting on http%s://%s:%s",
                "s" if ssl_config else "",
                settings.web_app_host,
                settings.web_app_port,
            )
        else:
            logger.info(
                "WEB_REGISTRATION_ENABLED is false. FastAPI server will not be started."
            )

    async def _start_teamtalk_service(self) -> None:
        self.tasks.append(
            asyncio.create_task(
                launch_teamtalk_service(
                    pytalk_bot_instance=self.pytalk_bot,  # Pass the instance
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

    async def _start_periodic_database_cleanup(self) -> None:
        self.tasks.append(
            asyncio.create_task(
                periodic_database_cleanup(),
                name="DatabaseCleanupTask",
            )
        )
        logger.info("Periodic database cleanup task created.")

    async def on_telegram_startup(self, dispatcher: Dispatcher) -> None:  # noqa: ARG002
        """Handles the startup logic, called by aiogram."""
        logger.info("Starting application components...")

        # 1. Initialize Database
        await init_db()
        logger.info("Database initialized.")

        # 2. Run admin ID cleanup
        await self._remove_admin_ids_from_registrations()

        # 3. Initialize PyTalk and start its service
        fastapi_app.state.pytalk_bot_instance = self.pytalk_bot
        await self._start_teamtalk_service()

        # 4. Start FastAPI server (if enabled)
        await self._start_fastapi_server()

        # 5. Start periodic database cleanup task
        await self._start_periodic_database_cleanup()

        logger.info("All background services started.")


    async def on_telegram_shutdown(self, dispatcher: Dispatcher) -> None:  # noqa: ARG002
        """Handles the shutdown logic, called by aiogram."""
        logger.info("Shutting down application components...")

        # 1. Cancel all running background tasks
        for task in self.tasks:
            if not task.done():
                logger.info("Cancelling task: %s", task.get_name())
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("All application tasks cancelled and awaited.")

        # 2. Close TeamTalk connection
        if self.pytalk_bot:
            await close_teamtalk_connection(self.pytalk_bot)
            logger.info("PyTalk bot connection closed.")

        # 3. Close database engine
        await close_db_engine()
        logger.info("Database engine closed.")

        logger.info("Application shutdown complete.")


    async def run(self) -> None:
        """Runs the application."""
        # Create PyTalk and Telegram Bot instances
        await self._init_pytalk_bot()
        await self._init_telegram_bot()

        if self.test_run:
            logger.info("Test run: Initializations complete. Exiting.")
            return

        if self.telegram_bot and self.dispatcher:
            try:
                # This call will now manage the entire lifecycle
                await self.dispatcher.start_polling(self.telegram_bot)
            finally:
                logger.info("Polling stopped. Closing bot session.")
                await self.telegram_bot.session.close()
                logger.info("Aiogram bot session closed.")
        else:
            logger.error(
                "Telegram Bot or Dispatcher not initialized. Cannot start polling."
            )


async def main() -> None:
    """The main function of the application."""
    logger.info("Application starting with arguments: %s", sys.argv)
    logger.info("NICK_NAME from config: %s", settings.nick_name)

    app = Application(test_run=args.test_run)
    await app.run()


if __name__ == "__main__":
    if sys.platform != "win32":
        try:
            import uvloop
            uvloop.install()
            logger.info("uvloop installed as the asyncio event loop policy.")
        except ImportError:
            logger.warning(
                "uvloop could not be imported. Using default asyncio event loop."
            )
        except Exception:
            logger.exception("Failed to install uvloop:")
    else:
        logger.info(
            "uvloop is not installed/used on Windows. Using default asyncio event loop."
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Application terminated by user (Ctrl+C).")
    except Exception:
        logger.exception("CRITICAL: Critical error during asyncio.run:")
