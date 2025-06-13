import asyncio
import logging

from bot.core import config as core_config
from bot.core.db import (
    cleanup_expired_download_tokens,
    cleanup_expired_pending_registrations,
    cleanup_expired_registered_ips,
    delete_expired_or_used_tokens,
)
from bot.core.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

async def periodic_database_cleanup(db_ready_event: asyncio.Event):
    """
    Periodically cleans up stale data from the database.
    Waits for the db_ready_event before starting its cycles.
    """
    logger.info("Starting periodic database cleanup task...")
    logger.info(f"Cleanup interval: {core_config.DB_CLEANUP_INTERVAL_SECONDS} seconds.")
    logger.info(f"Pending registration TTL: {core_config.DEFAULT_PENDING_REGISTRATION_TTL_SECONDS} seconds.")
    logger.info(f"Registered IP TTL: {core_config.DEFAULT_REGISTERED_IP_TTL_SECONDS} seconds.")

    logger.info("Database cleanup task waiting for database to be ready...")
    await db_ready_event.wait() # Wait for the event to be set
    logger.info("Database is ready, starting cleanup cycles.")

    while True:
        try:
            logger.info("Database cleanup cycle starting...")
            async with AsyncSessionLocal() as db:
                deleted_pending_regs = await cleanup_expired_pending_registrations(
                    db, older_than_seconds=core_config.DEFAULT_PENDING_REGISTRATION_TTL_SECONDS
                )
                if deleted_pending_regs > 0:
                    logger.info(f"Cleaned up {deleted_pending_regs} expired pending registrations.")

                deleted_ips = await cleanup_expired_registered_ips(
                    db, older_than_seconds=core_config.DEFAULT_REGISTERED_IP_TTL_SECONDS
                )
                if deleted_ips > 0:
                    logger.info(f"Cleaned up {deleted_ips} expired registered IPs.")

                deleted_tokens = await cleanup_expired_download_tokens(db)
                if deleted_tokens > 0:
                    logger.info(f"Cleaned up {deleted_tokens} expired or used download tokens.")

                deleted_deeplinks_count = await delete_expired_or_used_tokens(db)
                if deleted_deeplinks_count > 0:
                    logger.info(f"Periodic cleanup: Deleted {deleted_deeplinks_count} expired or used deeplink tokens.")
                else:
                    logger.debug("Periodic cleanup: No expired or used deeplink tokens to delete.")

                await db.commit() # Commit all changes made during this cleanup cycle
                logger.info("Database cleanup cycle finished.")

        except asyncio.CancelledError:
            logger.info("Periodic database cleanup task was cancelled. Exiting.")
            break  # Exit the loop if cancelled
        except Exception as e:
            logger.error(f"Error during database cleanup cycle: {e}", exc_info=True)
            # Decide if we should break the loop or continue after an error.
            # For now, it continues, but this could be made configurable or more robust.
            # If errors are frequent, the sleep interval will still apply before retrying.

        try:
            await asyncio.sleep(core_config.DB_CLEANUP_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Sleep in periodic database cleanup task was cancelled. Exiting.")
            break # Exit the loop if cancelled during sleep
