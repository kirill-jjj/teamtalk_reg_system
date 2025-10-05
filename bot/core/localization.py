"""Localization utilities for the bot application."""
import logging
from pathlib import Path
from typing import Any

import babel.support

from .config import settings

logger = logging.getLogger(__name__)

# Define LOCALES_DIR using pathlib.Path
LOCALES_DIR = Path(__file__).parent.parent.parent / "locales"
DEFAULT_LANG_CODE = 'en'

# Global store for available languages (list of dicts) and loaded translation objects
AVAILABLE_LANGUAGES_LIST = []
translations: dict[str, babel.support.Translations] = {}

def discover_available_languages() -> list[dict[str, str]]:
    """Discovers available languages by checking subdirectories in the LOCALES_DIR.

    A language is considered available if a messages.mo file exists.
    Tries to load the native name for each language.
    """
    discovered_languages = []
    if not LOCALES_DIR.is_dir():
        logger.error("Locales directory not found: %s", LOCALES_DIR)
        return discovered_languages

    for lang_code_dir in LOCALES_DIR.iterdir():
        if lang_code_dir.is_dir():
            lang_code = lang_code_dir.name
            messages_mo_path = lang_code_dir / "LC_MESSAGES" / "messages.mo"
            if messages_mo_path.exists() and messages_mo_path.is_file():
                native_name = lang_code.upper() # Default to uppercase lang_code
                try:
                    # Load just this specific language to get its native name
                    lang_translations = babel.support.Translations.load(
                        str(LOCALES_DIR), [lang_code]
                    )
                    # Attempt to get the translation for "native_language_name"
                    # This msgid should be defined in each messages.po file
                    translated_native_name = lang_translations.gettext(
                        "native_language_name"
                    )
                    if (translated_native_name and
                            translated_native_name != 'native_language_name'):
                        native_name = translated_native_name
                except Exception as e:
                    logger.warning(
                        "Could not load native name for language %s "
                        "from 'native_language_name': %s",
                        lang_code, e,
                    )

                discovered_languages.append(
                    {'code': lang_code, 'native_name': native_name}
                )
            else:
                logger.debug("No messages.mo file in %s, skipping.", lang_code_dir)
        else:
            logger.debug("Item %s is not a directory, skipping.", lang_code_dir)

    # If the default language is 'en' and it hasn't been added through a .mo file,
    # add it here silently, as we assume source strings are English.
    if (
        DEFAULT_LANG_CODE == 'en'
        and not any(lang['code'] == 'en' for lang in discovered_languages)
    ):
        discovered_languages.append({'code': 'en', 'native_name': 'English'})
        # Optionally, log at a debug level if confirmation of this path is needed.
    elif not any(lang['code'] == DEFAULT_LANG_CODE for lang in discovered_languages):
        # This case handles if DEFAULT_LANG_CODE is something other than 'en'
        # and is missing
        logger.info(
            "Default language '%s' not found in discovered languages. "
            "Adding it as a fallback.",
            DEFAULT_LANG_CODE,
        )
        discovered_languages.append(
            {
                'code': DEFAULT_LANG_CODE,
                'native_name': DEFAULT_LANG_CODE.upper() + " (Fallback)",
            }
        )

    logger.info("Discovered languages: %s", discovered_languages)
    return discovered_languages

def load_translations() -> None:
    """Loads translations for all discovered languages.

    Also populates AVAILABLE_LANGUAGES_LIST.
    """
    global translations, AVAILABLE_LANGUAGES_LIST  # noqa: PLW0603

    AVAILABLE_LANGUAGES_LIST = discover_available_languages()
    current_translations = {}

    for lang_info in AVAILABLE_LANGUAGES_LIST:
        lang_code = lang_info['code']
        try:
            loaded_translation = babel.support.Translations.load(
                str(LOCALES_DIR), [lang_code]
            )
            current_translations[lang_code] = loaded_translation
            logger.debug("Successfully loaded translation for '%s'.", lang_code)
        except Exception as e:
            logger.warning(
                "Could not load translation for language '%s': %s. "
                "Using NullTranslations.",
                lang_code,
                e,
            )
            current_translations[lang_code] = babel.support.NullTranslations()

    # Ensure DEFAULT_LANG_CODE (especially 'en') has at least NullTranslations
    # if not properly loaded
    if DEFAULT_LANG_CODE not in current_translations:
        # This block is a safeguard, typically hit if DEFAULT_LANG_CODE wasn't
        # in AVAILABLE_LANGUAGES_LIST
        # (e.g., discover_available_languages did not find it and its fallback
        # also didn't run, which is unlikely for 'en').
        # Or if it was in the list but failed loading so severely it wasn't even
        # set to NullTranslations in the loop (also unlikely).
        logger.warning(
            "Default language '%s' was not successfully processed or discovered. "
            "Ensuring it has a NullTranslations fallback.",
            DEFAULT_LANG_CODE,
        )
        current_translations[DEFAULT_LANG_CODE] = babel.support.NullTranslations()
        # Ensure it's in AVAILABLE_LANGUAGES_LIST for display consistency.
        if not any(
            lang['code'] == DEFAULT_LANG_CODE for lang in AVAILABLE_LANGUAGES_LIST
        ):
             logger.info(
                "Adding default language '%s' to available languages list "
                "for display (as fallback).",
                DEFAULT_LANG_CODE,
            )
             AVAILABLE_LANGUAGES_LIST.append(
                {
                    'code': DEFAULT_LANG_CODE,
                    'native_name': f"{DEFAULT_LANG_CODE.upper()} (Fallback)",
                }
            )

    translations = current_translations
    logger.info("Final available languages: %s", AVAILABLE_LANGUAGES_LIST)
    logger.info("Translations initialized for codes: %s", list(translations.keys()))

# Load translations at module import
load_translations()

def get_translator(lang_code: str | None = None) -> Any:  # noqa: ANN401
    """Returns a gettext-like translator function for the given language code.

    Falls back to DEFAULT_LANG_CODE if the requested language is not available.
    """
    selected_lang_code = lang_code
    if selected_lang_code not in translations:
        logger.debug(
            "Language '%s' not available, falling back to default '%s'.",
            selected_lang_code,
            DEFAULT_LANG_CODE,
        )
        selected_lang_code = DEFAULT_LANG_CODE

    translator_instance = translations.get(selected_lang_code)

    if not translator_instance:
        logger.error(
            "No translator instance found for '%s', even after fallback. "
            "Returning NullTranslations.gettext.",
            selected_lang_code,
        )
        return babel.support.NullTranslations().gettext

    return translator_instance.gettext

def get_admin_lang_code() -> str:
    """Gets the admin language code from config, validates against available languages.

    Falls back to DEFAULT_LANG_CODE if the admin's chosen language is not available.
    """
    # CFG_ADMIN_LANG is the language code string from config (e.g., "en", "RU")
    admin_lang_from_config = settings.bot_admin_lang # This comes from config
    if not admin_lang_from_config: # Should not happen given default in config
        admin_lang_from_config = DEFAULT_LANG_CODE

    # Normalize: take the first part of "en_US.UTF-8" -> "en", "ru_RU" -> "ru",
    # "RU" -> "ru"
    normalized_admin_lang = admin_lang_from_config.split('_')[0].split('.')[0].lower()

    if normalized_admin_lang in translations:
        return normalized_admin_lang  # Return the lowercase version
    logger.warning(
        "Admin language '%s' (normalized to '%s') from config is not available. "
        "Falling back to default language '%s'. "
        "Available languages: %s",
        admin_lang_from_config,
        normalized_admin_lang,
        DEFAULT_LANG_CODE,
        list(translations.keys()),
    )
    return DEFAULT_LANG_CODE

def get_available_languages_for_display() -> list[dict[str, str]]:
    """Returns the list of available languages with their codes and native names.

    This list is populated by load_translations.
    """
    return AVAILABLE_LANGUAGES_LIST

def refresh_translations() -> None:
    """Reloads all translations and re-discovers languages.

    Useful if language files are updated dynamically.
    """
    logger.info("Refreshing translations...")
    load_translations()

# Example of how to add "self_language_name_native" to your .po files:
#
# #: bot/core/localization.py:0
# # This line number is just illustrative, it can be any comment or not present
# msgid "self_language_name_native"
# msgstr "English" <--- For en/LC_MESSAGES/messages.po
#
# #: bot/core/localization.py:0
# msgid "self_language_name_native"
# msgstr "Русский" <--- For ru/LC_MESSAGES/messages.po
#
# Make sure to compile these .po files to .mo files.
# You would typically run a pybabel compile command.
# Example: pybabel compile -d locales
#
# Ensure this msgid is present in all .po files for each language.
# If missing, the native name will default to the uppercased language code.
