# Adding New Languages to the Application

This document outlines the process for adding translations for a new language to this application. Thanks to a dynamic language discovery system, code changes are generally not required to make the application aware of a new language.

## Steps to Add a New Language

Let's assume you want to add Spanish (language code `es`).

1.  **Create Language Directory Structure**:
    *   Navigate to the `locales/` directory in the project.
    *   Create a new directory for your language code: `locales/es/`
    *   Inside that, create the standard `LC_MESSAGES` directory: `locales/es/LC_MESSAGES/`

2.  **Initialize `.po` File**:
    *   Copy the template file `locales/messages.pot` into your new directory:
        ```bash
        cp locales/messages.pot locales/es/LC_MESSAGES/messages.po
        ```
    *   Alternatively, you can use `pybabel init` if you have it configured for the project:
        ```bash
        # Example, adjust if your setup differs
        # pybabel init -i locales/messages.pot -d locales -l es
        ```

3.  **Translate Strings in `.po` File**:
    *   Open `locales/es/LC_MESSAGES/messages.po` in a text editor that supports `.po` files (e.g., Poedit, or a plain text editor).
    *   For each `msgid "Some English String"`, provide the translation in the `msgstr "Translated String"` line.
    *   **Important - Native Language Name**: You **must** provide a translation for the `msgid "self_language_name_native"`. This translation should be the name of the language *in that language itself*. For Spanish, this would be:
        ```po
        #: bot/core/localization.py
        msgid "self_language_name_native"
        msgstr "Español"
        ```
        This is used to display the language correctly in language selection menus.
    *   Fill in other header information in the `.po` file if needed (like `Last-Translator`, `Language-Team`).

4.  **Compile `.po` to `.mo` File**:
    *   After translating, you need to compile the `.po` file into a binary `.mo` file, which the application uses.
    *   Use the `pybabel compile` command:
        ```bash
        pybabel compile -d locales
        ```
        This command will look for `.po` files in all language directories under `locales/` and compile them into `.mo` files in the same location (e.g., `locales/es/LC_MESSAGES/messages.mo`).
    *   Ensure you have Babel installed (`pip install Babel`).

5.  **Restart the Application**:
    *   The application discovers available languages at startup. Restart the bot for it to recognize the new language.

6.  **Verify**:
    *   Check the Telegram bot's language selection menu and the web interface's language dropdown. Your new language (e.g., "Español") should now appear as an option.
    *   Select it and test if your translated strings are being displayed.

## Updating Translations

If existing `msgid` strings in `messages.pot` change or new ones are added:

1.  **Update `.pot` file**: This is usually done by the developers by running `pybabel extract -F babel.cfg -o locales/messages.pot .`
2.  **Update your language's `.po` file**:
    ```bash
    pybabel update -i locales/messages.pot -d locales -l es
    ```
    (Replace `es` with your language code). This will merge new strings into your `.po` file and mark changed ones as fuzzy.
3.  Translate any new or fuzzy strings in your `.po` file.
4.  Compile to `.mo` again: `pybabel compile -d locales`.
5.  Restart the application.

---

By following these steps, your new language translations will be available in the application.
