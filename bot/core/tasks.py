import asyncio
import logging

from bot.core.config import settings
from bot.core.db.session import AsyncSessionLocal  # This one is fine as is

from .db.crud import (  # Changed to specific path
    cleanup_expired_download_tokens,
    cleanup_expired_pending_registrations,
    cleanup_expired_registered_ips,
    delete_expired_or_used_tokens,
)

logger = logging.getLogger(__name__)

async def periodic_database_cleanup(db_ready_event: asyncio.Event):
    """Periodically cleans up stale data from the database.
    Waits for the db_ready_event before starting its cycles.
    """
    logger.info("Starting periodic database cleanup task...")
    logger.info("Cleanup interval: %s seconds.", settings.db_cleanup_interval_seconds)
    logger.info("Pending registration TTL: %s seconds.", settings.pending_reg_ttl_seconds)
    logger.info("Registered IP TTL: %s seconds.", settings.registered_ip_ttl_seconds)

    logger.info("Database cleanup task waiting for database to be ready...")
    await db_ready_event.wait() # Wait for the event to be set
    logger.info("Database is ready, starting cleanup cycles.")

    while True:
        try:
            logger.info("Database cleanup cycle starting...")
            async with AsyncSessionLocal() as db:
                deleted_pending_regs = await cleanup_expired_pending_registrations(
                    db, older_than_seconds=settings.pending_reg_ttl_seconds
                )
                if deleted_pending_regs > 0:
                    logger.info("Cleaned up %s expired pending registrations.", deleted_pending_regs)

                deleted_ips = await cleanup_expired_registered_ips(
                    db, older_than_seconds=settings.registered_ip_ttl_seconds
                )
                if deleted_ips > 0:
                    logger.info("Cleaned up %s expired registered IPs.", deleted_ips)

                deleted_tokens = await cleanup_expired_download_tokens(db)
                if deleted_tokens > 0:
                    logger.info("Cleaned up %s expired or used download tokens.", deleted_tokens)

                deleted_deeplinks_count = await delete_expired_or_used_tokens(db)
                if deleted_deeplinks_count > 0:
                    logger.info("Periodic cleanup: Deleted %s expired or used deeplink tokens.", deleted_deeplinks_count)
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
            await asyncio.sleep(settings.db_cleanup_interval_seconds)
        except asyncio.CancelledError:
            logger.info("Sleep in periodic database cleanup task was cancelled. Exiting.")
            break # Exit the loop if cancelled during sleep
