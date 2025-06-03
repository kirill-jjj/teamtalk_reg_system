import asyncio
import logging # Reverted
import pytalk

logger = logging.getLogger(__name__) # Reverted

from aiogram import Bot as AiogramBot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.fsm.storage.base import StorageKey

from .handlers import registration as reg_handlers
# Import the router from registration.py
from .handlers.registration import router as registration_router
from .handlers import admin as admin_handlers
from ..core import config, database
from ..core import teamtalk_client as tt_client
from pytalk.message import Message as PyTalkMessage
from .states import RegistrationStates


# --- PyTalk Event Handlers ---
@tt_client.pytalk_bot.event
async def on_ready():
    logger.info("PyTalk Bot is ready (event received in telegram_bot.main).") # Removed await

@tt_client.pytalk_bot.event
async def on_my_login(server: pytalk.server.Server): # type: ignore
    logger.info(f"Successfully logged into TeamTalk server via PyTalk: {server.info.host} (event in telegram_bot.main)") # Removed await

@tt_client.pytalk_bot.event
async def on_message(message: PyTalkMessage):
    channel_name_info = "DM/Broadcast"
    if hasattr(message, 'channel') and message.channel:
        channel_name_info = message.channel.name
    elif isinstance(message, PyTalkMessage) and not hasattr(message, 'channel'):
        pass
        
    logger.info( # Removed await
        f"Received TeamTalk message via PyTalk: '{message.content}' "
        f"from user '{message.user.username if message.user else 'Unknown User'}' " # Добавил проверку на message.user
        f"in {channel_name_info}"
    )
    # Если нужно будет отправлять сообщения админам из этого хендлера,
    # экземпляр aiogram_bot нужно будет передавать сюда (например, через замыкание или класс)

# --- Aiogram Bot Setup and Run ---
async def run_telegram_bot() -> AiogramBot: # Функция теперь возвращает экземпляр бота
    await database.init_db()

    bot_instance = AiogramBot(token=config.TG_BOT_TOKEN) # Создаем экземпляр здесь
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)


    # Register handlers
    dp.message.register(reg_handlers.start_command_handler, Command("start"))
    dp.callback_query.register(
        reg_handlers.language_selection_handler,
        RegistrationStates.choosing_language,
        lambda c: c.data.startswith('set_lang_tg:')
    )
    dp.message.register(reg_handlers.username_handler, RegistrationStates.awaiting_username)
    dp.message.register(reg_handlers.password_handler, RegistrationStates.awaiting_password)
    dp.callback_query.register(
        reg_handlers.admin_verification_handler,
        lambda query: query.data.startswith("verify_reg:")
    )

    # Include the new router from registration.py (for nickname handlers)
    dp.include_router(registration_router)

    admin_handlers.register_admin_handlers(dp)

    logger.info("Telegram Bot Dispatcher configured. Starting polling...") # Removed await
    
    try:
        # This function prepares the bot and dispatcher; polling is initiated by run.py.
        return bot_instance, dp
    
    except Exception as e: # Хотя start_polling здесь не вызывается, оставим для общей структуры
        logger.exception("Error during Telegram bot setup (before polling):", exc_info=True) # Removed await
        # Если здесь произойдет ошибка, то bot_instance может не вернуться.
        # Это должно быть обработано в run.py
        raise # Перевыбрасываем исключение


async def start_telegram_polling(bot_instance: AiogramBot, dp: Dispatcher):
    """Отдельная функция для запуска polling."""
    try:
        await dp.start_polling(bot_instance, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot_instance.session.close()
        logger.info("Telegram Bot polling stopped and session closed.") # Removed await
        # Закрытие DB и PyTalk теперь будет в main finally блоке в run.py

async def start_pytalk_bot_internals():
    logger.info("Starting PyTalk bot internal event processing...") # Removed await
    try:
        async with tt_client.pytalk_bot:
            if not await tt_client.connect_to_teamtalk_server():
                logger.error("Failed to connect to TeamTalk server. PyTalk event processing might not work correctly.") # Removed await
            await tt_client.pytalk_bot._start()
            
    except Exception as e:
        logger.exception("Exception in PyTalk bot internal processing loop:", exc_info=True) # Removed await
    finally:
        logger.info("PyTalk bot internal event processing stopped.") # Removed await