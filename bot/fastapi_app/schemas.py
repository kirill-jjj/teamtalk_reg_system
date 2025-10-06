"""Pydantic schemas for the FastAPI application."""
from pydantic import BaseModel


class RegistrationPayload(BaseModel):
    """Schema for user registration data submitted via the web interface."""
    username: str
    password: str
    nickname: str | None = None


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


class Downloadables(BaseModel):
    """Schema for downloadable artefacts after registration."""

    tt_download_link_token: str | None
    tt_file_name_for_user: str | None
    client_zip_token: str | None
    client_zip_filename_for_user: str | None
    tt_quick_link: str | None
    file_generation_error: bool
