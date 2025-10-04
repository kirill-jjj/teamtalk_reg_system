"""Configuration module for the application.

This module uses Pydantic Settings to manage configuration. It loads settings
from a TOML file and environment variables, providing a single, type-hinted,
and validated source of truth for all configuration parameters.
"""

import logging
import os
from pathlib import Path
import tomllib
from typing import Any, ClassVar, Tuple

from pydantic import Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

logger = logging.getLogger(__name__)


class TomlConfigSettingsSource(PydanticBaseSettingsSource):
    """
    A settings source that loads variables from a TOML file.
    """

    def get_field_value(
        self, field: Field, field_name: str
    ) -> Tuple[Any, str, bool]:
        """
        Get field value from TOML file.
        """
        encoding = self.config.get("env_file_encoding")
        env_file = self.config.get("toml_file")
        if env_file:
            file_content_toml = tomllib.loads(env_file.read_text(encoding))
            field_value = file_content_toml.get(field_name)
            return field_value, field_name, False
        return None, field_name, False

    def prepare_field_value(
        self, field_name: str, field: Field, value: Any, value_is_complex: bool
    ) -> Any:
        """
        Prepare field value.
        """
        return value

    def __call__(self) -> dict[str, Any]:
        d: dict[str, Any] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            field_value, field_key, value_is_complex = self.get_field_value(
                field, field_name
            )
            field_value = self.prepare_field_value(
                field_name, field, field_value, value_is_complex
            )
            if field_value is not None:
                d[field_key] = field_value

        return d


class Settings(BaseSettings):
    """Defines the application settings, loaded from a TOML file and environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
        # The `toml_file` setting is a custom setting that we use in our custom source.
        toml_file=Path(os.getenv("CONFIG_FILE", "config.toml")),
    )

    # --- Telegram Bot Configuration ---
    tg_bot_token: str
    admin_ids: list[int] = Field(default_factory=list)

    # --- TeamTalk Server Configuration ---
    host_name: str
    port: int = Field(..., alias="PORT")  # Explicit alias for clarity
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
instantiate            "TRANSMIT_VOICE",
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
    web_app_host: str = "0.0.0.0"
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
        return (
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


try:
    settings = Settings()
    # Handle special case for UDP port if not provided
    if settings.udp_port is None:
        settings.udp_port = settings.port

    logger.info("Configuration loaded successfully using Pydantic Settings.")

except (ValidationError, FileNotFoundError) as e:
    if isinstance(e, FileNotFoundError) or "toml_file" in str(e):
        logger.error(
            f"Configuration file not found. Please create 'config.toml' or set the CONFIG_FILE environment variable. Error: {e}"
        )
    else:
        logger.error(f"Configuration validation error: {e}")
    # Exit if critical configuration is missing
    exit(1)