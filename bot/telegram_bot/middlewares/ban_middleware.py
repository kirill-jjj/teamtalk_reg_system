import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User # For type hinting event.from_user
from sqlalchemy.ext.asyncio import AsyncSession

# Assuming bot.core.db.crud is the correct path from this middleware's location
# If this file is in bot/telegram_bot/middlewares, then bot.core is one level up (..) then into core.
# So, from ...core.db.crud import is_user_banned might be more robust if project structure changes.
# For now, using the requested path.
from bot.core.db.crud import is_user_banned

logger = logging.getLogger(__name__)

class UserBanMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Try to get user from the event
        # The dispatcher populates 'event_from_user' for most common event types
        user: User | None = data.get("event_from_user")

        if user is None: # Should not happen for messages/callbacks typically handled by bots
            logger.debug("UserBanMiddleware: No 'event_from_user' in data, skipping ban check for event type: %s", type(event).__name__)
            return await handler(event, data)

        # DbSessionMiddleware should run before this and provide the session
        db_session: AsyncSession | None = data.get("db_session")
        if db_session is None:
            logger.warning("UserBanMiddleware: No 'db_session' in data for user %s, skipping ban check. Ensure DbSessionMiddleware runs before this.", user.id)
            return await handler(event, data)

        # Check if user is banned
        try:
            if await is_user_banned(db_session, user.id):
                logger.info(f"UserBanMiddleware: User {user.id} ({user.full_name}) is banned. Blocking event type: {type(event).__name__}.")
                # Stop processing this event for banned user.
                # Returning None effectively cancels the handling of this update.
                return None
        except Exception as e:
            logger.error(f"UserBanMiddleware: Error checking ban status for user {user.id}: {e}", exc_info=True)
            # If an error occurs during the ban check, it's safer to let the event through
            # rather than blocking a potentially non-banned user due to a system issue.
            # Depending on policy, this could also return None to block on error.
            return await handler(event, data)

        # If not banned, or if any error occurred above (and didn't return None)
        logger.debug(f"UserBanMiddleware: User {user.id} is not banned or check failed. Proceeding with handler for event type: {type(event).__name__}.")
        return await handler(event, data)
