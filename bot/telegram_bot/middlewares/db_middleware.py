"""This module provides a middleware for database sessions."""
from collections.abc import Awaitable, Callable
import logging
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

# Assuming AsyncSessionLocal is correctly exposed from the db setup
from ...core.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Middleware to provide a database session to handlers."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:  # noqa: ANN401
        """Provides a database session to the handler."""
        logger.debug("DbSessionMiddleware: Entered __call__")
        async with AsyncSessionLocal() as session:
            data["db_session"] = session
            try:
                logger.debug(
                    "DbSessionMiddleware: Passing control to handler. "
                    "Event type: %s, Data keys: %s",
                    type(event).__name__,
                    list(data.keys()),
                )
                result = await handler(event, data)
                logger.debug(
                    "DbSessionMiddleware: Handler executed successfully. "
                    "Attempting to commit session."
                )
                await session.commit()
                logger.debug("DbSessionMiddleware: Session committed successfully.")
            except Exception:
                logger.exception("Exception in handler, rolling back session:")
                await session.rollback()
                raise  # Re-raise the exception after rollback
            else:
                return result
            finally:
                logger.debug(
                    "DbSessionMiddleware: Exiting __call__ (session will be closed "
                    "by context manager)."
                )
