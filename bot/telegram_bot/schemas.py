"""This module contains the Pydantic models for the Telegram bot."""
from pydantic import BaseModel


class RegistrationStateData(BaseModel):
    """A Pydantic model for FSM context data during registration."""

    is_deeplink_registration: bool = False
    registrant_telegram_id: int | None = None
    selected_language: str | None = None
    is_admin_registrar: bool = False
    name: str | None = None  # Corresponds to the username
    password: str | None = None
    tt_account_type: str | None = None
    nickname: str | None = None
