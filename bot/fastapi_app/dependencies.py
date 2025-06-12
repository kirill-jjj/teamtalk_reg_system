from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.db.session import AsyncSessionLocal


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
