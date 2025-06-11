import logging
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

# Assuming session.py and models.py are in the same 'db' directory
from .session import AsyncSessionLocal
from .models import TelegramRegistration

logger = logging.getLogger(__name__)

async def is_telegram_id_registered(telegram_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        user = await session.get(TelegramRegistration, telegram_id)
        return user is not None

async def add_telegram_registration(telegram_id: int, teamtalk_username: str) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            new_registration = TelegramRegistration(telegram_id=telegram_id, teamtalk_username=teamtalk_username)
            session.add(new_registration)
            await session.commit()
            logger.info(f"Successfully registered Telegram ID {telegram_id} with TeamTalk username {teamtalk_username}")
            return True
        except SQLAlchemyIntegrityError:
            # It's good practice to log the specific error and context
            logger.warning(
                f"SQLAlchemyIntegrityError: Attempted to register Telegram ID {telegram_id} "
                f"or TeamTalk username '{teamtalk_username}' which likely already exists."
            )
            await session.rollback()
            return False
        except Exception as e:
            logger.error(f"Error adding Telegram registration to DB for {telegram_id} (username: {teamtalk_username}): {e}", exc_info=True)
            await session.rollback()
            return False

async def get_teamtalk_username_by_telegram_id(telegram_id: int) -> str | None:
    async with AsyncSessionLocal() as session:
        user = await session.get(TelegramRegistration, telegram_id)
        return user.teamtalk_username if user else None
