"""Configuration module for the application.

This module uses Pydantic Settings to manage configuration. It loads settings
from a TOML file and environment variables, providing a single, type-hinted,
and validated source of truth for all configuration parameters.
"""

import logging
import os
from pathlib import Path
import sys
import tomllib
from typing import Any

from pydantic import Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

logger = logging.getLogger(__name__)


class TomlConfigSettingsSource(PydanticBaseSettingsSource):
    """A settings source that loads variables from a TOML file."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        """Initializes the TOML config settings source."""
        super().__init__(settings_cls)
        toml_file_path_str = os.getenv("CONFIG_FILE", "config.toml")
        toml_file_path = Path(toml_file_path_str)

        logger.debug("Attempting to load TOML config from: '%s'", toml_file_path.absolute())
        if not toml_file_path.is_file():
            logger.debug("TOML config file not found at '%s'. is_file() returned False.", toml_file_path.absolute())
            self._toml_data = {}
        else:
            logger.debug("TOML config file found at '%s'. Loading...", toml_file_path.absolute())
            try:
                with toml_file_path.open("rb") as f:
                    self._toml_data = tomllib.load(f)
            except Exception:
                logger.exception("Error loading TOML file '%s'.", toml_file_path)
                self._toml_data = {}

    def get_field_value(
        self, field_name: str
    ) -> tuple[Any, str, bool]:
        """Get field value from the pre-loaded TOML data."""
        field_value = self._toml_data.get(field_name)
        return field_value, field_name, False

    def __call__(self) -> dict[str, Any]:
        """Returns the TOML data as a dictionary."""
        return self._toml_data


class Settings(BaseSettings):
    """Defines the application settings, loaded from a TOML file and environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
    )

    # --- Telegram Bot Configuration ---
    tg_bot_token: str
    admin_ids: list[int] = Field(default_factory=list)

    # --- TeamTalk Server Configuration ---
    host_name: str
    port: int
    udp_port: int | None = None
    user_name: str
    password: str
    nick_name: str = "RegisterBot"
    client_name: str = "PyTalkRegisterBot"
    encrypted: bool = False
    server_name: str = "TeamTalk Server"

    # --- TeamTalk Bot Account Specific Configuration ---
    tt_public_hostname: str | None = None
    tt_join_channel: str | None = None
    tt_join_channel_password: str = ""
    tt_status_text: str = ""
    tt_gender: str = "neutral"

    # --- Registration Settings ---
    verify_registration: bool = False
    bot_admin_lang: str = "en"
    force_user_lang: str | None = ""
    teamtalk_default_user_rights: list[str] = Field(
        default=[
            "MULTI_LOGIN",
            "VIEW_ALL_USERS",
            "CREATE_TEMPORARY_CHANNEL",
            "UPLOAD_FILES",
            "DOWNLOAD_FILES",
            "TRANSMIT_VOICE",
            "TRANSMIT_VIDEOCAPTURE",
            "TRANSMIT_DESKTOP",
            "TRANSMIT_DESKTOPINPUT",
            "TRANSMIT_MEDIAFILE",
            "TEXTMESSAGE_USER",
            "TEXTMESSAGE_CHANNEL",
        ]
    )
    teamtalk_registration_broadcast_enabled: bool = True

    # --- Web Application (FastAPI) Configuration ---
    web_registration_enabled: bool = False
    web_app_host: str = "0.0.0.0"  # noqa: S104
    web_app_port: int = 5000
    root_path: str = ""
    web_app_ssl_enabled: bool = False
    web_app_ssl_cert_path: str | None = None
    web_app_ssl_key_path: str | None = None

    # --- Uvicorn Proxy Headers Configuration ---
    web_app_forwarded_allow_ips: str = "*"
    web_app_proxy_headers: bool = True

    # --- Advanced/Optional Settings ---
    teamtalk_client_template_dir: str | None = None
    generated_file_ttl_seconds: int = 600
    db_name: str = "users.db"

    # --- Telegram Bot Registration Modes ---
    telegram_deeplink_registration_enabled: bool = False
    telegram_public_registration_enabled: bool = True

    # --- Database Cleanup Task Configuration ---
    pending_reg_ttl_seconds: int = 604800  # 7 days
    registered_ip_ttl_seconds: int = 2592000  # 30 days
    db_cleanup_interval_seconds: int = 3600  # 1 hour

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customizes the order and inclusion of settings sources."""
        return (
            init_settings,
            TomlConfigSettingsSource(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

try:
    settings = Settings()
    # Handle special case for UDP port if not provided
    if settings.udp_port is None:
        settings.udp_port = settings.port

    logger.info("Configuration loaded successfully.")

except (ValidationError, FileNotFoundError) as e:
    if isinstance(e, FileNotFoundError):
        logger.exception("Configuration file not found. Please create 'config.toml' or set the CONFIG_FILE environment variable.")
    else:
        logger.exception("Configuration validation error.")
    # Exit if critical configuration is missing
    sys.exit(1)
