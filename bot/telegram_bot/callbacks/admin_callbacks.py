from aiogram.filters.callback_data import CallbackData

class AdminDeleteCallback(CallbackData, prefix="admin_del"):
    # user_telegram_id is the ID of the user TO BE DELETED
    user_telegram_id: int

class AdminBanListActionCallback(CallbackData, prefix="admin_banlist"):
    action: str  # "view", "unban", "add_prompt"
    # target_telegram_id is the ID of the user in the ban list context
    target_telegram_id: int | None = None

class AdminTTAccountsCallback(CallbackData, prefix="admin_tt_acc"):
    action: str  # e.g., "list_all", "delete_prompt", "delete_confirm"
    # tt_username will be used to identify the account for deletion
    tt_username: str | None = None

# Add any other admin-related CallbackData classes here if they exist
# and were contributing to a circular import or are better organized here.
