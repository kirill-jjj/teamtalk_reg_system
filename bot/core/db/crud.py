"""CRUD operations for database models."""

from datetime import UTC, datetime, timedelta
import logging

from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from bot.core.config import settings
from bot.utils.schemas import SourceInfo

from .models import (
    BannedUser,  # Added BannedUser import
    DeeplinkToken,
    FastapiDownloadToken,
    FastapiRegisteredIp,
    PendingTelegramRegistration,
    TelegramRegistration,
)

logger = logging.getLogger(__name__)

# Existing functions ...

async def is_telegram_id_registered(session: AsyncSession, telegram_id: int) -> bool:
    """Checks if a Telegram ID is already registered."""
    user = await session.get(TelegramRegistration, telegram_id)
    return user is not None

async def add_telegram_registration(
    session: AsyncSession, telegram_id: int, teamtalk_username: str
) -> TelegramRegistration | None:
    """Adds a new Telegram registration to the database."""
    if telegram_id in settings.admin_ids:
        logger.warning(
            "Attempt to register an admin ID (%s) was blocked. User: %s",
            telegram_id, teamtalk_username
        )
        return None

    try:
        new_registration = TelegramRegistration(
            telegram_id=telegram_id, teamtalk_username=teamtalk_username
        )
        session.add(new_registration)
        await session.flush()
        # Flush to get instance persisted for return or catch error
        logger.info(
            "Successfully added Telegram ID %s with TeamTalk username %s to session.",
            telegram_id, teamtalk_username
        )
    except SQLAlchemyIntegrityError:
        logger.warning(
            "SQLAlchemyIntegrityError during add operation for Telegram ID %s "
            "or TeamTalk username '%s'. This usually means it already exists.",
            telegram_id,
            teamtalk_username,
        )
        await session.rollback()  # Rollback before re-raising for clarity
        raise
    except Exception:
        logger.exception(
            "Error adding Telegram registration to session for %s (username: %s):",
            telegram_id, teamtalk_username
        )
        await session.rollback()
        raise
    return new_registration

async def get_teamtalk_username_by_telegram_id(
    session: AsyncSession, telegram_id: int
) -> str | None:
    """Retrieves the TeamTalk username for a given Telegram ID."""
    user = await session.get(TelegramRegistration, telegram_id)
    return user.teamtalk_username if user else None


async def get_all_telegram_registrations(
    db_session: AsyncSession
) -> list[TelegramRegistration]:
    """Retrieves all entries from the TelegramRegistration table."""
    stmt = select(TelegramRegistration)
    result = await db_session.execute(stmt)
    users = result.scalars().all()
    logger.info("Retrieved %s Telegram registrations.", len(users))
    return users


async def get_user_by_identifier(
    db_session: AsyncSession, identifier: str
) -> TelegramRegistration | None:
    """Retrieves a user by Telegram ID (if identifier is numeric).

    or TeamTalk username.
    """
    stmt = None
    if identifier.isdigit():
        try:
            telegram_id = int(identifier)
            stmt = select(TelegramRegistration).where(
                TelegramRegistration.telegram_id == telegram_id
            )
            logger.info("Attempting to find user by Telegram ID: %s", telegram_id)
        except ValueError:
            # This case should ideally not be hit if isdigit() is true,
            # but as a safeguard.
            logger.warning(
                "Identifier '%s' is all digits but failed to convert to int.",
                identifier
            )
            # Fallback to searching by username if conversion failed unexpectedly.
            stmt = select(TelegramRegistration).where(
                TelegramRegistration.teamtalk_username == identifier
            )
            logger.info(
                "Attempting to find user by TeamTalk username (fallback): %s",
                identifier
            )
    else:
        stmt = select(TelegramRegistration).where(
            TelegramRegistration.teamtalk_username == identifier
        )
        logger.info("Attempting to find user by TeamTalk username: %s", identifier)

    if stmt is not None:
        result = await db_session.execute(stmt)
        user = result.scalars().first()
        if user:
            logger.info("User found: %s / %s", user.telegram_id, user.teamtalk_username)
            return user
        logger.info("User not found with identifier: %s", identifier)
        return None
    return None # Should not be reached if logic is correct, but as a failsafe.


async def delete_telegram_registration(
    db_session: AsyncSession, telegram_id: int
) -> bool:
    """Deletes a user from the TelegramRegistration table based on.

    telegram_id and commits.
    """
    logger.info("Attempting to delete registration for Telegram ID: %s", telegram_id)
    stmt = delete(TelegramRegistration).where(
        TelegramRegistration.telegram_id == telegram_id
    )
    result = await db_session.execute(stmt)
    if result.rowcount > 0:
        await db_session.commit()
        logger.info(
            "Successfully deleted registration for Telegram ID: %s. Rows affected: %s",
            telegram_id, result.rowcount
        )
        return True
    logger.info("No registration found for Telegram ID: %s to delete.", telegram_id)
    return False


async def delete_telegram_registration_by_id(
    session: AsyncSession, telegram_id: int
) -> bool:
    """Deletes a TelegramRegistration record by telegram_id."""
    logger.info("Attempting to delete registration for Telegram ID: %s", telegram_id)
    stmt = delete(TelegramRegistration).where(
        TelegramRegistration.telegram_id == telegram_id
    )
    result = await session.execute(stmt)
    # This version does not commit, relying on the caller to manage the transaction.
    if result.rowcount > 0:
        logger.info(
            "Successfully marked registration for deletion for Telegram ID: %s. "
            "Rows affected: %s. Commit pending.",
            telegram_id, result.rowcount
        )
        return True
    logger.info("No registration found for Telegram ID: %s to delete.", telegram_id)
    return False

# --- PendingTelegramRegistration CRUD ---

async def add_pending_telegram_registration(
    db: AsyncSession,
    request_key: str,
    registrant_telegram_id: int,
    username: str,
    password_cleartext: str,
    nickname: str,
    source_info: "SourceInfo",
) -> PendingTelegramRegistration:
    """Adds a new pending Telegram registration to the database."""
    pending_reg = PendingTelegramRegistration(
        request_key=request_key,
        registrant_telegram_id=registrant_telegram_id,
        username=username,
        password_cleartext=password_cleartext,
        nickname=nickname,
        source_info=source_info.model_dump(exclude_unset=True),
    )
    db.add(pending_reg)
    await db.flush() # To ensure it's added and get ID, or raise error
    await db.refresh(pending_reg) # To get defaults like created_at loaded
    logger.info("Added pending registration for request_key: %s", request_key)
    return pending_reg

async def get_and_remove_pending_telegram_registration(
    db: AsyncSession, request_key: str
) -> PendingTelegramRegistration | None:
    """Retrieves and removes a pending Telegram registration by its request key."""
    stmt = select(PendingTelegramRegistration).where(
        PendingTelegramRegistration.request_key == request_key
    )
    result = await db.execute(stmt)
    pending_reg = result.scalars().first()
    if pending_reg:
        await db.delete(pending_reg)
        await db.flush()  # Ensure delete is processed
        logger.info("Removed pending registration for request_key: %s", request_key)
        return pending_reg
    logger.info("No pending registration found for request_key: %s", request_key)
    return None

async def cleanup_expired_pending_registrations(
    db: AsyncSession, older_than_seconds: int
) -> int:
    """Cleans up expired pending Telegram registrations."""
    expiration_time = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    stmt = delete(PendingTelegramRegistration).where(
        PendingTelegramRegistration.created_at < expiration_time
    )
    result = await db.execute(stmt)
    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info(
            "Cleaned up %s expired pending registrations older than %s seconds.",
            deleted_count, older_than_seconds
        )
    return deleted_count

# --- FastapiRegisteredIp CRUD ---

async def add_fastapi_registered_ip(
    db: AsyncSession, ip_address: str, username: str | None = None
) -> FastapiRegisteredIp:
    """Adds a new FastAPI registered IP to the database."""
    # This will attempt to add, or do nothing if IP already exists (PK constraint)
    # For robust "upsert" or update timestamp on conflict, more complex logic
    # or DB-specific syntax is needed. Here, we assume we just want to record
    # it if not present, or let it fail if it is. A get before add could also
    # work to update timestamp if desired. For now, let's keep it simple: add
    # if new, or let IntegrityError be caught by caller if it's a duplicate.
    registered_ip = FastapiRegisteredIp(
        ip_address=ip_address,
        username=username,
        registration_timestamp=datetime.now(UTC),
    )
    db.add(registered_ip)
    try:
        await db.flush()
        await db.refresh(registered_ip)
        logger.info(
            "Added registered IP: %s for user: %s",
            ip_address, username if username else 'N/A'
        )
    except SQLAlchemyIntegrityError:
        await db.rollback() # Rollback the specific failed add
        # Re-raise for now, as the current requirement is just to add.
        logger.warning("IP address %s already registered.", ip_address)
        raise # Or handle as an update if that's the desired behavior for duplicates.
    return registered_ip


async def is_fastapi_ip_registered(db: AsyncSession, ip_address: str) -> bool:
    """Checks if a FastAPI IP address is already registered."""
    stmt = select(FastapiRegisteredIp).where(
        FastapiRegisteredIp.ip_address == ip_address
    )
    result = await db.execute(stmt)
    return result.scalars().first() is not None

async def cleanup_expired_registered_ips(
    db: AsyncSession, older_than_seconds: int
) -> int:
    """Cleans up expired registered IP addresses."""
    expiration_time = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    stmt = delete(FastapiRegisteredIp).where(
        FastapiRegisteredIp.registration_timestamp < expiration_time
    )
    result = await db.execute(stmt)
    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info(
            "Cleaned up %s expired registered IPs older than %s seconds.",
            deleted_count, older_than_seconds
        )
    return deleted_count

# --- FastapiDownloadToken CRUD ---

async def add_fastapi_download_token(
    db: AsyncSession,
    token: str,
    filepath_on_server: str,
    original_filename: str,
    token_type: str,
    expires_at: datetime
) -> FastapiDownloadToken:
    """Adds a new FastAPI download token to the database."""
    download_token = FastapiDownloadToken(
        token=token,
        filepath_on_server=filepath_on_server,
        original_filename=original_filename,
        token_type=token_type,
        expires_at=expires_at
    )
    db.add(download_token)
    await db.flush()
    await db.refresh(download_token)
    logger.info("Added download token: %s for file: %s", token, original_filename)
    return download_token

async def get_fastapi_download_token(
    db: AsyncSession, token: str
) -> FastapiDownloadToken | None:
    """Retrieves a valid FastAPI download token."""
    stmt = select(FastapiDownloadToken).where(FastapiDownloadToken.token == token)
    result = await db.execute(stmt)
    token_entry = result.scalars().first()
    if token_entry:
        if token_entry.expires_at < datetime.now(UTC):
            logger.info("Download token %s found but has expired.", token)
            return None
        if token_entry.is_used:
            logger.info("Download token %s found but has already been used.", token)
            return None  # Or handle as per requirements for used tokens
        logger.info("Valid download token %s retrieved.", token)
        return token_entry
    logger.info("Download token %s not found.", token)
    return None

async def mark_fastapi_download_token_used(
    db: AsyncSession, token: str
) -> bool:
    """Marks a FastAPI download token as used if it's valid and not already used."""
    stmt = select(FastapiDownloadToken).where(FastapiDownloadToken.token == token)
    result = await db.execute(stmt)
    token_entry = result.scalars().first()
    if (
        token_entry
        and not token_entry.is_used
        and token_entry.expires_at >= datetime.now(UTC)
    ):
        token_entry.is_used = True
        await db.flush()
        logger.info("Marked download token %s as used.", token)
        return True
    logger.info(
        "Download token %s not found, expired, or already used. Cannot mark as used.",
        token
    )
    return False

async def remove_fastapi_download_token(db: AsyncSession, token: str) -> bool:
    """Removes a FastAPI download token from the database."""
    stmt = delete(FastapiDownloadToken).where(FastapiDownloadToken.token == token)
    result = await db.execute(stmt)
    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info("Removed download token: %s", token)
        return True
    logger.info("Download token %s not found for removal.", token)
    return False

async def cleanup_expired_download_tokens(db: AsyncSession) -> int:
    """Cleans up expired or used FastAPI download tokens."""
    now = datetime.now(UTC)
    # Also remove used tokens even if not expired, as they are no longer needed
    stmt = delete(FastapiDownloadToken).where(
        (FastapiDownloadToken.expires_at < now) | (FastapiDownloadToken.is_used)
    )
    result = await db.execute(stmt)
    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info("Cleaned up %s expired or used download tokens.", deleted_count)
    return deleted_count


# --- DeeplinkToken CRUD ---

async def create_deeplink_token(
    db: AsyncSession, token_str: str, expires_at: datetime,
    generated_by_admin_id: int | None = None
) -> DeeplinkToken:
    """Creates a new deeplink token."""
    new_token = DeeplinkToken(
        token=token_str,
        expires_at=expires_at,
        generated_by_admin_id=generated_by_admin_id
    )
    db.add(new_token)
    await db.commit()
    # Commit to make it available for refresh and subsequent operations
    await db.refresh(new_token)
    logger.info("Created deeplink token: %s expiring at %s", token_str, expires_at)
    return new_token

async def get_valid_deeplink_token(
    db: AsyncSession, token_str: str
) -> DeeplinkToken | None:
    """Retrieves a valid, unused, and unexpired deeplink token."""
    stmt = select(DeeplinkToken).where(
        DeeplinkToken.token == token_str,
        not DeeplinkToken.is_used,
        DeeplinkToken.expires_at > datetime.now(UTC)
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()
    if token:
        logger.info("Valid deeplink token found: %s", token_str)
    else:
        # It's useful to know why it wasn't valid for debugging, but avoid
        # being too verbose in standard operation. A more detailed check
        # could be added if needed, e.g., checking if it exists but is
        # used/expired.
        logger.info(
            "No valid deeplink token found for: %s (either not found, "
            "already used, or expired).",
            token_str
        )
    return token

async def mark_deeplink_token_as_used(
    db: AsyncSession, token_obj: DeeplinkToken
) -> DeeplinkToken:
    """Marks a deeplink token as used."""
    if token_obj: # Ensure the object exists before trying to modify it
        token_obj.is_used = True
        await db.commit() # Commit the change
        await db.refresh(token_obj) # Refresh to get the updated state from DB
        logger.info("Marked deeplink token as used: %s", token_obj.token)
    return token_obj

async def delete_expired_or_used_tokens(db: AsyncSession) -> int:
    """Deletes expired or used deeplink tokens from the database."""
    # Delete used tokens first
    stmt_delete_used = delete(DeeplinkToken).where(DeeplinkToken.is_used)
    result_used = await db.execute(stmt_delete_used)

    # Then delete expired tokens (that might not have been marked as used)
    # This ensures all non-valid tokens are cleaned up.
    # Using current time directly in the query
    stmt_delete_expired = delete(DeeplinkToken).where(
        DeeplinkToken.expires_at <= datetime.now(UTC)
    )
    result_expired = await db.execute(stmt_delete_expired)

    deleted_count = result_used.rowcount + result_expired.rowcount
    if deleted_count > 0:
        await db.commit() # Commit if any deletions occurred
        logger.info("Deleted %s expired or used deeplink tokens.", deleted_count)
    return deleted_count


# --- BannedUser CRUD ---

async def add_banned_user(
    db_session: AsyncSession,
    telegram_id: int,
    teamtalk_username: str | None = None,
    admin_id: int | None = None,
    reason: str | None = None
) -> BannedUser:
    """Adds or updates a banned user record."""
    # Check if already banned, if so, update; otherwise, create new.
    # This is an upsert-like behavior.
    stmt = select(BannedUser).where(BannedUser.telegram_id == telegram_id)
    result = await db_session.execute(stmt)
    banned_user = result.scalar_one_or_none()

    if banned_user:
        banned_user.teamtalk_username = (
            teamtalk_username if teamtalk_username is not None
            else banned_user.teamtalk_username
        )
        banned_user.banned_at = datetime.now(UTC)  # Update ban time
        banned_user.banned_by_admin_id = (
            admin_id if admin_id is not None
            else banned_user.banned_by_admin_id
        )
        banned_user.reason = reason if reason is not None else banned_user.reason
        logger.info("Updating existing ban for Telegram ID: %s", telegram_id)
    else:
        banned_user = BannedUser(
            telegram_id=telegram_id,
            teamtalk_username=teamtalk_username,
            banned_by_admin_id=admin_id,
            reason=reason
            # banned_at is defaulted in model
        )
        db_session.add(banned_user)
        logger.info("Adding new ban for Telegram ID: %s", telegram_id)

    await db_session.commit()
    await db_session.refresh(banned_user) # Refresh to get DB defaults like banned_at
    return banned_user

async def remove_banned_user(db_session: AsyncSession, telegram_id: int) -> bool:
    """Removes a banned user record from the database."""
    stmt = delete(BannedUser).where(BannedUser.telegram_id == telegram_id)
    result = await db_session.execute(stmt)
    await db_session.commit()
    if result.rowcount > 0:
        logger.info("Removed ban for Telegram ID: %s", telegram_id)
        return True
    logger.info("No ban found for Telegram ID: %s to remove.", telegram_id)
    return False

async def is_user_banned(db_session: AsyncSession, telegram_id: int) -> bool:
    """Checks if a user is banned."""
    stmt = select(BannedUser).where(BannedUser.telegram_id == telegram_id)
    # Efficiently check for existence without loading the object
    result = await db_session.execute(select(stmt.exists()))
    return result.scalar_one()

async def get_banned_users(db_session: AsyncSession) -> list[BannedUser]:
    """Retrieves all banned users from the database."""
    stmt = select(BannedUser).order_by(desc(BannedUser.banned_at))
    result = await db_session.execute(stmt)
    return list(result.scalars().all()) # Ensure it's a list, not just an iterable

async def get_telegram_id_by_teamtalk_username(
    db_session: AsyncSession, teamtalk_username: str
) -> int | None:
    """Retrieves the Telegram ID associated with a given TeamTalk username."""
    # This function assumes TelegramRegistration table links TT usernames and TG IDs
    stmt = select(TelegramRegistration.telegram_id).where(
        TelegramRegistration.teamtalk_username == teamtalk_username
    )
    result = await db_session.execute(stmt)
    telegram_id = result.scalar_one_or_none()
    if telegram_id:
        logger.debug(
            "Found Telegram ID %s for TeamTalk username '%s'.",
            telegram_id,
            teamtalk_username,
        )
    else:
        logger.debug("No Telegram ID for TT username '%s'.", teamtalk_username)
    return telegram_id
