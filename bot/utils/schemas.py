"""This module contains Pydantic models for the bot."""
from pydantic import BaseModel


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
