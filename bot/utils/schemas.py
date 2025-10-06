"""This module contains Pydantic models for the bot."""
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class TTConnectionInfo(BaseModel):
    """Pydantic model for TeamTalk connection information."""

    server_name: str
    host: str
    tcpport: int
    udpport: int
    encrypted: bool


class TTUserInfo(BaseModel):
    """Pydantic model for TeamTalk user information."""

    username: str
    password: str
    nickname: str | None = None


class TelegramSourceInfo(BaseModel):
    """Model for registration source information from Telegram."""

    type: Literal["telegram"] = "telegram"
    telegram_id: int
    telegram_full_name: str
    telegram_username: str | None
    selected_language: str | None
    nickname: str | None = None
    is_deeplink_registration: bool = False
    is_admin_registrar: bool
    tt_account_type: str | None
    registrar_telegram_id: int


class WebSourceInfo(BaseModel):
    """Model for registration source information from the web interface."""

    type: Literal["web"] = "web"
    ip_address: str
    user_lang: str
    nickname: str | None


SourceInfo = Annotated[
    TelegramSourceInfo | WebSourceInfo,
    Field(discriminator="type"),
]


class TeamTalkRegistrationArtefacts(BaseModel):
    """Schema for data returned after a successful TeamTalk registration."""

    username: str
    password: str
    final_nickname: str
    effective_hostname: str
    server_name: str
    tcp_port: int
    udp_port: int
    encrypted: bool


class TeamTalkServerInfo(BaseModel):
    """Pydantic model for TeamTalk server connection information."""
    host_name: str
    tcp_port: int
    udp_port: int
    user_name: str
    password: str
    nickname: str
    encrypted: bool
    join_channel_path: str | None
    join_channel_pass: str
    bot_gender: str
    bot_status_text: str
