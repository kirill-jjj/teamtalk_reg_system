import gettext
import os
from .config import ENV_LANG_NUMERIC # Убедись, что этот импорт корректен для твоей структуры

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCALE_DIR = os.path.join(APP_DIR, 'locales')

# Языки, которые мы поддерживаем
# fallback=True означает, что если перевод не найден, будет использован оригинальный текст (msgid)
# или если .mo файл для языка отсутствует, будет использован язык по умолчанию.
translations = {}

def load_translations():
    global translations
    for lang_code in ['en', 'ru']:
        try:
            translations[lang_code] = gettext.translation('messages', localedir=LOCALE_DIR, languages=[lang_code])
        except FileNotFoundError:
            if lang_code == 'en': # English is the source language, so provide a dummy identity translator
                translations['en'] = gettext.NullTranslations()
            else: # For other languages, if .mo is missing, log warning or fallback to English
                print(f"Warning: Translation file for language '{lang_code}' not found. Falling back.")
                if 'en' in translations: # Fallback to English if its dummy/real translation exists
                     translations[lang_code] = translations['en']
                else: # Ultimate fallback if even English dummy is missing
                    translations[lang_code] = gettext.NullTranslations()
    if not translations.get('en'): # Ensure English always has at least a NullTranslations
        translations['en'] = gettext.NullTranslations()


load_translations() # Загружаем переводы при импорте модуля

DEFAULT_LANG_CODE = 'en'

def get_translator(lang_code: str = None):
    selected_lang = lang_code
    if selected_lang not in translations:
        selected_lang = DEFAULT_LANG_CODE
    
    # Если даже после fallback'а нет 'en', возвращаем NullTranslations, чтобы избежать ошибки
    return translations.get(selected_lang, gettext.NullTranslations()).gettext

def get_admin_lang_code():
    return 'ru' if ENV_LANG_NUMERIC == "1" else 'en'

def refresh_translations():
    """Перезагружает переводы. Может быть полезно при динамическом обновлении."""
    load_translations()