from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, DateTime, JSON, Boolean, BigInteger, Column
from datetime import datetime

class Base(DeclarativeBase):
    pass

class TelegramRegistration(Base):
    __tablename__ = "telegram_registrations"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False) # Changed Integer to BigInteger
    teamtalk_username: Mapped[str] = mapped_column(String, nullable=False, unique=True)

class PendingTelegramRegistration(Base):
    __tablename__ = "pending_telegram_registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    request_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    registrant_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String, index=True, nullable=False)
    password_cleartext: Mapped[str] = mapped_column(String, nullable=False)
    nickname: Mapped[str] = mapped_column(String, nullable=False)
    source_info: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True, nullable=False)

class FastapiRegisteredIp(Base):
    __tablename__ = "fastapi_registered_ips"

    ip_address: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, nullable=True)
    registration_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class FastapiDownloadToken(Base):
    __tablename__ = "fastapi_download_tokens"

    token: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    filepath_on_server: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    token_type: Mapped[str] = mapped_column(String, nullable=False) # e.g., 'tt_config', 'client_zip'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
