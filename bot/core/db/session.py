import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Assuming config.py is in the parent directory 'core' relative to 'db' directory.
# If bot.core.config is the reliable absolute path, that could be used too.
# The previous subtask used `from .config import DB_NAME_CONFIG` when modifying database.py
# which was in the same dir as config.py. Now session.py is in a 'db' subdirectory.
# So, `from ..config import DB_NAME_CONFIG` should be correct.
from ..config import DB_NAME_CONFIG
from .models import Base # Base is now in models.py in the same 'db' directory

logger = logging.getLogger(__name__)

DB_ASYNC_URL = f"sqlite+aiosqlite:///{DB_NAME_CONFIG}"

async_engine = create_async_engine(DB_ASYNC_URL)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized.")

async def close_db_engine():
    if async_engine: # Check if async_engine is not None
        await async_engine.dispose()
        logger.info("Database engine disposed.")
    else:
        logger.info("Database engine was not initialized, no need to dispose.")
