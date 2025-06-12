from aiogram.filters.callback_data import CallbackData


# CallbackData classes for registration flow
class LanguageCallback(CallbackData, prefix="reg_lang"): # Changed prefix for clarity
    action: str # e.g., "select"
    language_code: str

class NicknameChoiceCallback(CallbackData, prefix="reg_nick_choice"): # Changed prefix
    action: str  # e.g., "provide", "generate"

class AdminVerificationCallback(CallbackData, prefix="reg_admin_verify"): # Changed prefix
    action: str  # e.g., "verify", "reject"
    request_key: str # Corresponds to the string key in pending_telegram_registrations table

class TTAccountTypeCallback(CallbackData, prefix="reg_tt_type"): # Changed prefix
    action: str # e.g., "select"
    account_type: str  # e.g., "admin", "user"
