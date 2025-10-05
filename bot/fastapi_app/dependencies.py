"""Dependencies for the FastAPI application."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.db.session import AsyncSessionLocal


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session for FastAPI routes."""
    async with AsyncSessionLocal() as session:
        yield session
