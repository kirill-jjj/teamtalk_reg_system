import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.config import ADMIN_IDS
from .models import TelegramRegistration, PendingTelegramRegistration, FastapiRegisteredIp, FastapiDownloadToken

logger = logging.getLogger(__name__)

# Existing functions ...

async def is_telegram_id_registered(session: AsyncSession, telegram_id: int) -> bool:
    user = await session.get(TelegramRegistration, telegram_id)
    return user is not None

async def add_telegram_registration(session: AsyncSession, telegram_id: int, teamtalk_username: str) -> Optional[TelegramRegistration]:
    if telegram_id in ADMIN_IDS:
        logger.warning(f"Attempt to register an admin ID ({telegram_id}) was blocked. User: {teamtalk_username}")
        return None

    try:
        new_registration = TelegramRegistration(telegram_id=telegram_id, teamtalk_username=teamtalk_username)
        session.add(new_registration)
        await session.flush() # Flush to get instance persisted for return or catch error
        logger.info(f"Successfully added Telegram ID {telegram_id} with TeamTalk username {teamtalk_username} to session.")
        return new_registration
    except SQLAlchemyIntegrityError:
        logger.warning(
            f"SQLAlchemyIntegrityError during add operation for Telegram ID {telegram_id} "
            f"or TeamTalk username '{teamtalk_username}'. This usually means it already exists."
        )
        await session.rollback() # Rollback before re-raising for clarity, though middleware might also do it
        raise
    except Exception as e:
        logger.error(f"Error adding Telegram registration to session for {telegram_id} (username: {teamtalk_username}): {e}", exc_info=True)
        await session.rollback()
        raise

async def get_teamtalk_username_by_telegram_id(session: AsyncSession, telegram_id: int) -> str | None:
    user = await session.get(TelegramRegistration, telegram_id)
    return user.teamtalk_username if user else None

async def delete_telegram_registration_by_id(session: AsyncSession, telegram_id: int) -> bool:
    '''Deletes a TelegramRegistration record by telegram_id.'''
    logger.info(f"Attempting to delete registration for Telegram ID: {telegram_id}")
    stmt = delete(TelegramRegistration).where(TelegramRegistration.telegram_id == telegram_id)
    result = await session.execute(stmt)
    # await session.flush() # Not strictly necessary for delete if not immediately checking, but good practice
    if result.rowcount > 0:
        logger.info(f"Successfully deleted registration for Telegram ID: {telegram_id}. Rows affected: {result.rowcount}")
        return True
    logger.info(f"No registration found for Telegram ID: {telegram_id} to delete.")
    return False

# --- PendingTelegramRegistration CRUD ---

async def add_pending_telegram_registration(
    db: AsyncSession,
    request_key: str,
    registrant_telegram_id: int,
    username: str,
    password_cleartext: str,
    nickname: str,
    source_info: Dict[str, Any]
) -> PendingTelegramRegistration:
    pending_reg = PendingTelegramRegistration(
        request_key=request_key,
        registrant_telegram_id=registrant_telegram_id,
        username=username,
        password_cleartext=password_cleartext,
        nickname=nickname,
        source_info=source_info
    )
    db.add(pending_reg)
    await db.flush() # To ensure it's added and get ID, or raise error
    await db.refresh(pending_reg) # To get defaults like created_at loaded
    logger.info(f"Added pending registration for request_key: {request_key}")
    return pending_reg

async def get_and_remove_pending_telegram_registration(
    db: AsyncSession, request_key: str
) -> Optional[PendingTelegramRegistration]:
    stmt = select(PendingTelegramRegistration).where(PendingTelegramRegistration.request_key == request_key)
    result = await db.execute(stmt)
    pending_reg = result.scalars().first()
    if pending_reg:
        await db.delete(pending_reg)
        await db.flush() # Ensure delete is processed
        logger.info(f"Retrieved and removed pending registration for request_key: {request_key}")
        return pending_reg
    logger.info(f"No pending registration found for request_key: {request_key}")
    return None

async def cleanup_expired_pending_registrations(db: AsyncSession, older_than_seconds: int) -> int:
    expiration_time = datetime.utcnow() - timedelta(seconds=older_than_seconds)
    stmt = delete(PendingTelegramRegistration).where(PendingTelegramRegistration.created_at < expiration_time)
    result = await db.execute(stmt)
    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} expired pending registrations older than {older_than_seconds} seconds.")
    return deleted_count

# --- FastapiRegisteredIp CRUD ---

async def add_fastapi_registered_ip(
    db: AsyncSession, ip_address: str, username: Optional[str] = None
) -> FastapiRegisteredIp:
    # This will attempt to add, or do nothing if IP already exists (PK constraint)
    # For robust "upsert" or update timestamp on conflict, more complex logic or DB-specific syntax is needed.
    # Here, we assume we just want to record it if not present, or let it fail if it is.
    # A get before add could also work to update timestamp if desired.
    # For now, let's keep it simple: add if new, or let IntegrityError be caught by caller if it's a duplicate.
    registered_ip = FastapiRegisteredIp(ip_address=ip_address, username=username, registration_timestamp=datetime.utcnow())
    db.add(registered_ip)
    try:
        await db.flush()
        await db.refresh(registered_ip)
        logger.info(f"Added registered IP: {ip_address} for user: {username if username else 'N/A'}")
    except SQLAlchemyIntegrityError:
        await db.rollback() # Rollback the specific failed add
        # Re-raise for now, as the current requirement is just to add.
        logger.warning(f"IP address {ip_address} already registered.")
        raise # Or handle as an update if that's the desired behavior for duplicates.
    return registered_ip


async def is_fastapi_ip_registered(db: AsyncSession, ip_address: str) -> bool:
    stmt = select(FastapiRegisteredIp).where(FastapiRegisteredIp.ip_address == ip_address)
    result = await db.execute(stmt)
    return result.scalars().first() is not None

async def cleanup_expired_registered_ips(db: AsyncSession, older_than_seconds: int) -> int:
    expiration_time = datetime.utcnow() - timedelta(seconds=older_than_seconds)
    stmt = delete(FastapiRegisteredIp).where(FastapiRegisteredIp.registration_timestamp < expiration_time)
    result = await db.execute(stmt)
    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} expired registered IPs older than {older_than_seconds} seconds.")
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
    logger.info(f"Added download token: {token} for file: {original_filename}")
    return download_token

async def get_fastapi_download_token(db: AsyncSession, token: str) -> Optional[FastapiDownloadToken]:
    stmt = select(FastapiDownloadToken).where(FastapiDownloadToken.token == token)
    result = await db.execute(stmt)
    token_entry = result.scalars().first()
    if token_entry:
        if token_entry.expires_at < datetime.utcnow():
            logger.info(f"Download token {token} found but has expired.")
            # Optionally delete it here or let cleanup handle it
            # await db.delete(token_entry)
            # await db.flush()
            return None
        if token_entry.is_used:
            logger.info(f"Download token {token} found but has already been used.")
            return None # Or handle as per requirements for used tokens
        logger.info(f"Valid download token {token} retrieved.")
        return token_entry
    logger.info(f"Download token {token} not found.")
    return None

async def mark_fastapi_download_token_used(db: AsyncSession, token: str) -> bool:
    stmt = select(FastapiDownloadToken).where(FastapiDownloadToken.token == token)
    result = await db.execute(stmt)
    token_entry = result.scalars().first()
    if token_entry and not token_entry.is_used and token_entry.expires_at >= datetime.utcnow():
        token_entry.is_used = True
        await db.flush()
        logger.info(f"Marked download token {token} as used.")
        return True
    logger.info(f"Download token {token} not found, expired, or already used. Cannot mark as used.")
    return False

async def remove_fastapi_download_token(db: AsyncSession, token: str) -> bool:
    stmt = delete(FastapiDownloadToken).where(FastapiDownloadToken.token == token)
    result = await db.execute(stmt)
    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info(f"Removed download token: {token}")
        return True
    logger.info(f"Download token {token} not found for removal.")
    return False

async def cleanup_expired_download_tokens(db: AsyncSession) -> int:
    now = datetime.utcnow()
    # Also remove used tokens even if not expired, as they are no longer needed
    stmt = delete(FastapiDownloadToken).where(
        (FastapiDownloadToken.expires_at < now) | (FastapiDownloadToken.is_used == True)
    )
    result = await db.execute(stmt)
    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} expired or used download tokens.")
    return deleted_count
