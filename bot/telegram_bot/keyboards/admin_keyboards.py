from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ...core.localization import get_translator, get_admin_lang_code # Added imports

# Define the callback data for the button
CALLBACK_DATA_DELETE_USER = "admin_delete_user_start"
KEY_BUTTON_DELETE_USER = "admin_keyboard_delete_user" # Localization key

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    """
    Returns an inline keyboard with admin-specific actions, currently "Delete User".
    """
    _ = get_translator(get_admin_lang_code()) # Get translator
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_(KEY_BUTTON_DELETE_USER), # Use localized text
        callback_data=CALLBACK_DATA_DELETE_USER
    )
    # Adjust layout if more buttons are added in the future.
    # For a single button, builder.adjust(1) is implicit.
    return builder.as_markup()

# Example of how this might be used (not part of the file's direct functionality but for clarity):
# async def some_handler(message: types.Message):
#     keyboard = get_admin_panel_keyboard()
#     await message.answer("Admin Panel:", reply_markup=keyboard)
