"""Database session and engine setup for the application."""
import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from ..config import settings

logger = logging.getLogger(__name__)

DB_ASYNC_URL = f"sqlite+aiosqlite:///{settings.db_name}"

async_engine = create_async_engine(DB_ASYNC_URL)


# Enable WAL mode for SQLite
@event.listens_for(async_engine.sync_engine, "connect")
def _enable_wal(dbapi_connection: Any, connection_record: Any) -> None:  # noqa: ARG001, ANN401
    cursor = dbapi_connection.cursor()
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        logger.info("SQLite WAL mode enabled.")
    finally:
        cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, expire_on_commit=False, class_=AsyncSession
)


async def init_db() -> None:
    """Initializes the database by creating all tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database initialized.")


async def close_db_engine() -> None:
    """Closes the database engine."""
    if async_engine:  # Check if async_engine is not None
        await async_engine.dispose()
        logger.info("Database engine disposed.")
    else:
        logger.info("Database engine was not initialized, no need to dispose.")
