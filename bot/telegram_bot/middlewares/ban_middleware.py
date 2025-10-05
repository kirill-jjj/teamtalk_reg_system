"""This module provides a middleware for banning users."""
from collections.abc import Awaitable, Callable
import logging
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User  # For type hinting event.from_user
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.db.crud import is_user_banned

logger = logging.getLogger(__name__)


class UserBanMiddleware(BaseMiddleware):
    """Middleware to check if a user is banned."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:  # noqa: ANN401
        """Checks if a user is banned and blocks the event if they are."""
        user: User | None = data.get("event_from_user")

        if user is None:
            logger.debug(
                "UserBanMiddleware: No 'event_from_user' in data, "
                "skipping ban check for event type: %s",
                type(event).__name__,
            )
            return await handler(event, data)

        db_session: AsyncSession | None = data.get("db_session")
        if db_session is None:
            logger.warning(
                "UserBanMiddleware: No 'db_session' in data for user %s, "
                "skipping ban check. Ensure DbSessionMiddleware runs before this.",
                user.id,
            )
            return await handler(event, data)

        try:
            if await is_user_banned(db_session, user.id):
                logger.info(
                    "UserBanMiddleware: User %s (%s) is banned. "
                    "Blocking event type: %s.",
                    user.id,
                    user.full_name,
                    type(event).__name__,
                )
                return None
        except Exception:
            logger.exception(
                "UserBanMiddleware: Error checking ban status for user %s:", user.id
            )
            return await handler(event, data)

        logger.debug(
            "UserBanMiddleware: User %s is not banned or check failed. "
            "Proceeding with handler for event type: %s.",
            user.id,
            type(event).__name__,
        )
        return await handler(event, data)
