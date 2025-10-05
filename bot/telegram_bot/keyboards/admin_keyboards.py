"""This module provides keyboards for the admin panel."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ...core.localization import get_admin_lang_code, get_translator
from ..callbacks.admin_callbacks import (
    AdminBanListActionCallback,
    AdminTTAccountsCallback,
)

# Define the callback data for the button
CALLBACK_DATA_DELETE_USER = (
    "admin_delete_user_start"  # String callback for deleting TG user by TG ID
)

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    """Returns an inline keyboard with admin-specific actions."""
    _ = get_translator(get_admin_lang_code())  # Get translator
    builder = InlineKeyboardBuilder()

    # Button for deleting users (existing)
    builder.button(text=_("Delete User"), callback_data=CALLBACK_DATA_DELETE_USER)

    # New button for managing ban list
    builder.button(
        text=_("Manage Ban List"),
        callback_data=AdminBanListActionCallback(
            action="view", target_telegram_id=None
        ).pack(),
    )

    # New button for listing all TeamTalk accounts
    builder.button(
        text=_("List TeamTalk Accounts"),
        callback_data=AdminTTAccountsCallback(
            action="list_all", tt_username=None
        ).pack(),
    )

    builder.adjust(1)  # Arrange buttons in a single column
    return builder.as_markup()
