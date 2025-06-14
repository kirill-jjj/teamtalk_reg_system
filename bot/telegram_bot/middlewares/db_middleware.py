import logging
from typing import Any, Awaitable, Callable, Dict

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
        logger.debug("DbSessionMiddleware: Entered __call__")
        async with AsyncSessionLocal() as session:
            data["db_session"] = session
            try:
                logger.debug(f"DbSessionMiddleware: Passing control to handler. Event type: {type(event).__name__}, Data keys: {list(data.keys())}")
                result = await handler(event, data)
                logger.debug("DbSessionMiddleware: Handler executed successfully. Attempting to commit session.")
                # Assuming commit is desired if handler completes without error.
                # For more fine-grained control, handlers could manage their own commits
                # and the middleware would only handle session closing and rollback on error.
                # However, a common pattern is for the middleware to manage the transaction scope.
                await session.commit()
                logger.debug("DbSessionMiddleware: Session committed successfully.")
                return result
            except Exception as e:
                logger.error(f"Exception in handler, rolling back session: {e}", exc_info=True)
                await session.rollback()
                raise # Re-raise the exception after rollback
            finally:
                # This block executes whether an exception occurred or not,
                # as long as the session was established.
                # The session is automatically closed by the 'async with' context manager.
                logger.debug("DbSessionMiddleware: Exiting __call__ (session will be closed by context manager).")
