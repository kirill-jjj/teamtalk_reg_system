import logging
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Assuming session.py and models.py are in the same 'db' directory
from .session import AsyncSessionLocal # This might become unused if AsyncSessionLocal is only used by middleware
from .models import TelegramRegistration

logger = logging.getLogger(__name__)

async def is_telegram_id_registered(session: AsyncSession, telegram_id: int) -> bool:
    user = await session.get(TelegramRegistration, telegram_id)
    return user is not None

async def add_telegram_registration(session: AsyncSession, telegram_id: int, teamtalk_username: str) -> bool:
    try:
        new_registration = TelegramRegistration(telegram_id=telegram_id, teamtalk_username=teamtalk_username)
        session.add(new_registration)
        # The flush is often useful to ensure any immediate DB constraints are checked
        # or to get IDs for newly created objects if needed before a full commit.
        # However, if not strictly necessary, it can be omitted and the middleware's commit will handle it.
        # For now, let's keep it simple and rely on the middleware's commit.
        # await session.flush() # Optional: if you need to check for errors like IntegrityError here specifically
        logger.info(f"Successfully added Telegram ID {telegram_id} with TeamTalk username {teamtalk_username} to session.")
        return True
    except SQLAlchemyIntegrityError:
        logger.warning(
            f"SQLAlchemyIntegrityError during add operation for Telegram ID {telegram_id} "
            f"or TeamTalk username '{teamtalk_username}'. This usually means it already exists."
        )
        # No rollback here, let the middleware handle it if the exception propagates
        raise # Re-raise to allow middleware to handle rollback
    except Exception as e:
        logger.error(f"Error adding Telegram registration to session for {telegram_id} (username: {teamtalk_username}): {e}", exc_info=True)
        # No rollback here, let the middleware handle it
        raise # Re-raise to allow middleware to handle rollback

async def get_teamtalk_username_by_telegram_id(session: AsyncSession, telegram_id: int) -> str | None:
    user = await session.get(TelegramRegistration, telegram_id)
    return user.teamtalk_username if user else None
