import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

# Assuming AsyncSessionLocal is correctly exposed from the db setup
from ...core.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with AsyncSessionLocal() as session:
            data["db_session"] = session
            try:
                result = await handler(event, data)
                # Assuming commit is desired if handler completes without error.
                # For more fine-grained control, handlers could manage their own commits
                # and the middleware would only handle session closing and rollback on error.
                # However, a common pattern is for the middleware to manage the transaction scope.
                await session.commit()
                return result
            except Exception as e:
                logger.error(f"Exception in handler, rolling back session: {e}", exc_info=True)
                await session.rollback()
                raise # Re-raise the exception after rollback
            # The session is automatically closed by the context manager 'async with AsyncSessionLocal() as session:'
            # No explicit session.close() is needed here due to the context manager.
