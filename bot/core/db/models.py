from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Column
from sqlmodel import Field, SQLModel


class TelegramRegistration(SQLModel, table=True):
    __tablename__ = "telegram_registrations"

    telegram_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=False),
    )
    teamtalk_username: str = Field(unique=True)


class PendingTelegramRegistration(SQLModel, table=True):
    __tablename__ = "pending_telegram_registrations"

    id: int | None = Field(default=None, primary_key=True, index=True)
    request_key: str = Field(unique=True, index=True)
    registrant_telegram_id: int = Field(sa_column=Column(BigInteger, index=True))
    username: str = Field(index=True)
    password_cleartext: str
    nickname: str
    source_info: dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class FastapiRegisteredIp(SQLModel, table=True):
    __tablename__ = "fastapi_registered_ips"

    ip_address: str = Field(primary_key=True, index=True)
    username: str | None = Field(default=None)
    registration_timestamp: datetime = Field(
        default_factory=datetime.utcnow, index=True
    )


class FastapiDownloadToken(SQLModel, table=True):
    __tablename__ = "fastapi_download_tokens"

    token: str = Field(primary_key=True, index=True)
    filepath_on_server: str
    original_filename: str
    token_type: str  # e.g., 'tt_config', 'client_zip'
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    expires_at: datetime = Field(index=True)
    is_used: bool = Field(default=False, index=True)


class DeeplinkToken(SQLModel, table=True):
    __tablename__ = "deeplink_tokens"

    id: int | None = Field(default=None, primary_key=True, index=True)
    token: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(index=True)
    is_used: bool = Field(default=False, index=True)
    generated_by_admin_id: int | None = Field(default=None)


class BannedUser(SQLModel, table=True):
    __tablename__ = "banned_users"

    telegram_id: int = Field(
        sa_column=Column(BigInteger, primary_key=True, autoincrement=False)
    )
    teamtalk_username: str | None = Field(default=None, index=True)
    banned_at: datetime = Field(default_factory=datetime.utcnow)
    banned_by_admin_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    reason: str | None = Field(default=None)
