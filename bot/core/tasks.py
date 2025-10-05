"""Background tasks for the bot application."""
import asyncio
import logging

from bot.core.config import settings
from bot.core.db.session import AsyncSessionLocal

from .db.crud import (
    cleanup_expired_download_tokens,
    cleanup_expired_pending_registrations,
    cleanup_expired_registered_ips,
    delete_expired_or_used_tokens,
)

logger = logging.getLogger(__name__)

async def periodic_database_cleanup() -> None:
    """Periodically cleans up stale data from the database."""
    logger.info("Starting periodic database cleanup task...")
    logger.info("Cleanup interval: %s seconds.", settings.db_cleanup_interval_seconds)
    logger.info("Pending reg TTL: %s seconds.", settings.pending_reg_ttl_seconds)
    logger.info("Registered IP TTL: %s seconds.", settings.registered_ip_ttl_seconds)

    while True:
        try:
            logger.info("Database cleanup cycle starting...")
            async with AsyncSessionLocal() as db:
                deleted_pending_regs = await cleanup_expired_pending_registrations(
                    db, older_than_seconds=settings.pending_reg_ttl_seconds
                )
                if deleted_pending_regs > 0:
                    logger.info(
                        "Cleaned up %s expired pending regs.", deleted_pending_regs
                    )

                deleted_ips = await cleanup_expired_registered_ips(
                    db, older_than_seconds=settings.registered_ip_ttl_seconds
                )
                if deleted_ips > 0:
                    logger.info("Cleaned up %s expired registered IPs.", deleted_ips)

                deleted_tokens = await cleanup_expired_download_tokens(db)
                if deleted_tokens > 0:
                    logger.info(
                        "Cleaned up %s expired/used download tokens.", deleted_tokens
                    )

                deleted_deeplinks_count = await delete_expired_or_used_tokens(db)
                if deleted_deeplinks_count > 0:
                    logger.info(
                        "Periodic cleanup: Deleted %s expired/used deeplink tokens.",
                        deleted_deeplinks_count,
                    )
                else:
                    logger.debug(
                        "Periodic cleanup: No expired/used deeplink tokens to delete."
                    )

                await db.commit() # Commit all changes made during this cleanup cycle
                logger.info("Database cleanup cycle finished.")

        except asyncio.CancelledError:
            logger.info("Periodic database cleanup task was cancelled. Exiting.")
            break  # Exit the loop if cancelled
        except Exception:
            logger.exception("Error during database cleanup cycle:")

        try:
            await asyncio.sleep(settings.db_cleanup_interval_seconds)
        except asyncio.CancelledError:
            logger.info(
                "Sleep in periodic database cleanup task was cancelled. Exiting."
            )
            break # Exit the loop if cancelled during sleep
