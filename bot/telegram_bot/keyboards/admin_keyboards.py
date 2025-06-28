from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ...core.localization import get_translator, get_admin_lang_code
from ...core import config # Import config to check WEB_REGISTRATION_ENABLED

from ..callbacks.admin_callbacks import AdminBanListActionCallback, AdminTTAccountsCallback, AdminWebApprovalCallback # Import new CallbackData

# Define the callback data for the button
CALLBACK_DATA_DELETE_USER = "admin_delete_user_start" # String callback for deleting TG user by TG ID
KEY_BUTTON_DELETE_USER = "admin_keyboard_delete_user"
KEY_BUTTON_MANAGE_BAN_LIST = "admin_button_manage_ban_list"
KEY_BUTTON_LIST_TT_ACCOUNTS = "admin_button_list_tt_accounts" # New localization key
KEY_BUTTON_PENDING_WEB_REGS = "admin_button_pending_web_regs" # New localization key for web approvals

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    """
    Returns an inline keyboard with admin-specific actions.
    """
    _ = get_translator(get_admin_lang_code()) # Get translator
    builder = InlineKeyboardBuilder()

    # Button for deleting users (existing)
    builder.button(
        text=_(KEY_BUTTON_DELETE_USER),
        callback_data=CALLBACK_DATA_DELETE_USER
    )

    # New button for managing ban list
    builder.button(
        text=_(KEY_BUTTON_MANAGE_BAN_LIST),
        callback_data=AdminBanListActionCallback(action="view", target_telegram_id=None).pack()
    )

    # New button for listing all TeamTalk accounts
    builder.button(
        text=_(KEY_BUTTON_LIST_TT_ACCOUNTS),
        callback_data=AdminTTAccountsCallback(action="list_all", tt_username=None).pack()
    )

    # Conditionally add button for Pending Web Registrations
    if config.WEB_REGISTRATION_ENABLED:
        builder.button(
            text=_(KEY_BUTTON_PENDING_WEB_REGS),
            callback_data=AdminWebApprovalCallback(action="view_pending", request_id=None).pack() # request_id can be None or 0 for a general view action
        )

    builder.adjust(1) # Arrange buttons in a single column
    return builder.as_markup()

# Example of how this might be used (not part of the file's direct functionality but for clarity):
# async def some_handler(message: types.Message):
#     keyboard = get_admin_panel_keyboard()
#     await message.answer("Admin Panel:", reply_markup=keyboard)
