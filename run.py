import asyncio
import logging
import threading

from bot.core import config as core_config
# Импортируем функции, а не глобальную переменную
from bot.telegram_bot.main import run_telegram_bot, start_pytalk_bot_internals, start_telegram_polling
from bot.web_app.main import create_flask_app, run_flask_app
from bot.core.database import close_db_engine
from bot.core.teamtalk_client import shutdown_pytalk_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("pytalk").setLevel(logging.INFO)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting application...")

    tasks = []
    actual_aiogram_bot_instance = None # Для хранения экземпляра бота

    try:
        # Сначала настраиваем бота и получаем его экземпляр и диспетчер
        actual_aiogram_bot_instance, dp = await run_telegram_bot()
        
        # Теперь создаем задачу для polling Telegram
        telegram_polling_task = asyncio.create_task(
            start_telegram_polling(actual_aiogram_bot_instance, dp), 
            name="TelegramBotPolling"
        )
        tasks.append(telegram_polling_task)
        
        # Задача для PyTalk
        pytalk_task = asyncio.create_task(start_pytalk_bot_internals(), name="PyTalkBotInternals")
        tasks.append(pytalk_task)

        flask_thread = None
        if core_config.FLASK_REGISTRATION_ENABLED:
            logger.info("Flask registration is enabled. Initializing Flask app.")
            
            if actual_aiogram_bot_instance is None: # Дополнительная проверка
                logger.error("Aiogram bot instance not properly initialized for Flask app. Flask notifications might fail.")
            
            loop = asyncio.get_running_loop()
            flask_app = create_flask_app(actual_aiogram_bot_instance, loop) # Передаем экземпляр
            
            flask_thread = threading.Thread(target=run_flask_app, args=(flask_app,), daemon=True, name="FlaskThread")
            flask_thread.start()
            logger.info(f"Flask app started in a separate thread. Accessible at http://{core_config.FLASK_HOST}:{core_config.FLASK_PORT}/register") # Убрал /web_registration
        else:
            logger.info("Flask registration is disabled.")

        # Ожидаем завершения основных асинхронных задач
        await asyncio.gather(*tasks, return_exceptions=True)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down...")
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
        
        # Flask-поток является daemon, он завершится вместе с основным потоком.
        # cleanup_flask_resources вызывается в finally блока run_flask_app.
        if flask_thread and flask_thread.is_alive():
             logger.info("Flask thread is a daemon and will terminate with the main application.")

        logger.info("Application shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user (Ctrl+C in asyncio.run).")
    except Exception as e:
        logger.critical(f"Critical error during asyncio.run: {e}", exc_info=True)
        