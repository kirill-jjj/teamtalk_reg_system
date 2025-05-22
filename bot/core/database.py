import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

from .config import TG_BOT_TOKEN # just to ensure config is loaded, not used directly here

logger = logging.getLogger(__name__)

DB_NAME = "users.db"
DB_ASYNC_URL = f"sqlite+aiosqlite:///{DB_NAME}"

async_engine = create_async_engine(DB_ASYNC_URL)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

class TelegramRegistration(Base):
    __tablename__ = "telegram_registrations"

    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    teamtalk_username: Mapped[str] = mapped_column(String, nullable=False, unique=True) # Added unique=True for username

async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized.")

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
            logger.warning(f"SQLAlchemyIntegrityError: Attempted to re-register Telegram ID {telegram_id} or username {teamtalk_username} which already exists.")
            await session.rollback()
            return False
        except Exception as e:
            logger.error(f"Error adding Telegram registration to DB for {telegram_id} (username: {teamtalk_username}): {e}")
            await session.rollback()
            return False

async def get_teamtalk_username_by_telegram_id(telegram_id: int) -> str | None:
    async with AsyncSessionLocal() as session:
        user = await session.get(TelegramRegistration, telegram_id)
        return user.teamtalk_username if user else None

async def close_db_engine():
    if async_engine:
        await async_engine.dispose()
        logger.info("Database engine disposed.")