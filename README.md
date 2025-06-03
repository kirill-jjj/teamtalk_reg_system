# TeamTalk Registration System Bot

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![GitHub repository](https://img.shields.io/badge/GitHub-Repo-blue.svg)](https://github.com/kirill-jjj/teamtalk_reg_system)

A comprehensive bot solution for self-registration on TeamTalk 5 servers, featuring both a Telegram bot interface and an optional Flask-based web registration portal. This project aims to simplify user onboarding for TeamTalk communities.

## Why This Bot?

By default, TeamTalk server administrators are solely responsible for creating new user accounts. This can be a bottleneck for growing communities or for servers where administrators aren't always available. The TeamTalk Registration System Bot empowers users to register themselves, streamlining the process. This bot is distributed under the GPLv3 license, ensuring it remains free and open-source software.

It allows users to register:
*   Via a Telegram bot, with an optional admin approval step.
*   Via a web page (FastAPI-based), with IP-based registration limiting.

## Features

*   **Telegram Bot Registration:**
    *   User-friendly registration flow.
    *   Language selection (English/Russian).
    *   Optional admin approval for new registrations.
    *   Automatic generation and delivery of `.tt` connection files and quick-connect links.
*   **Web Registration (FastAPI):**
    *   Optional, can be enabled/disabled via configuration (`WEB_REGISTRATION_ENABLED`).
    *   Language selection on the web page (English/Russian).
    *   IP-based registration limiting.
    *   Automatic generation and delivery of `.tt` connection files and quick-connect links.
    *   Optional: Download pre-configured TeamTalk client (ZIP) if a template is provided.
*   **Configuration:**
    *   Easy setup using a `.env` file.
    *   Configurable TeamTalk server details, admin IDs, registration verification, etc.
*   **Localization:**
    *   User interface available in English and Russian (powered by Gettext `.po` files, easily extendable).
*   **TeamTalk Integration:**
    *   Uses `py-talk-ex` library for robust TeamTalk SDK interaction.
    *   Checks for existing usernames on the TeamTalk server.
    *   Broadcasts new registrations to admins on the TeamTalk server.
*   **Database:**
    *   SQLite database (via SQLAlchemy and aiosqlite) to track Telegram user registrations and prevent multiple accounts per Telegram ID.

## Installation

These instructions assume you have Python 3.11+ installed.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/kirill-jjj/teamtalk_reg_system.git
    cd teamtalk_reg_system
    ```

2.  **Install `uv`**

    If you don't have `uv` installed (a fast Python package installer and resolver), you can install it as follows:

    *   **For Linux and macOS:**
        ```bash
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # After installation, you might need to source your shell's rc file or open a new terminal.
        # Or, run the command suggested by the installer, often:
        source $HOME/.local/bin/env
        ```
    *   **For Windows:**
        The simplest method if you have Python and pip installed is:
        ```bash
        pip install uv
        ```
        For other installation methods (e.g., via an installer), please refer to the [official Astral `uv` documentation](https://astral.sh/uv).

    Make sure `uv` is accessible in your PATH. You can check this by running `uv --version`.

3.  **Install dependencies and set up the environment using `uv`:**
    This command will create a virtual environment (e.g., in a `.venv` folder) if one doesn't exist, and then synchronize the environment with the dependencies specified in `pyproject.toml` (and potentially `uv.lock` if present).
    ```bash
    uv sync
    ```
    To include development dependencies (like `pytest` for testing), use:
    ```bash
    uv sync --dev
    ```
    This ensures your environment has all necessary packages for both running the application and developing/testing it.

4.  **Compile Localization Files**

    This project uses Babel for internationalization. To make sure all text strings are correctly displayed in the supported languages (English and Russian), you need to compile the localization files.

    Activate your virtual environment (e.g., `source .venv/bin/activate` on Linux/macOS or `.\.venv\Scripts\activate` on Windows if not already active). Then run the following command from the root directory of the project:
    ```bash
    pybabel compile -D messages -d locales
    ```
    This will compile the `.po` files into `.mo` files, which are used by the application.

    *(Optional) If you make changes to the translatable strings in the Python code or Jinja2 templates, you'll need to update the translation files:*
    1.  *Extract messages to update the `.pot` template file:*
        ```bash
        pybabel extract -F babel.cfg -o locales/messages.pot .
        ```
    2.  *Update the language-specific `.po` files (e.g., for Russian):*
        ```bash
        pybabel update -i locales/messages.pot -d locales -l ru
        ```
    *After updating the `.po` files with translations, re-run the `compile` command.*

5.  **Configure the bot:**
    *   Rename `.env.example` to `.env`.
    *   Open the `.env` file with a text editor and fill in your specific details (see `.env.example` for required fields and descriptions). Key settings include:
        *   `TG_BOT_TOKEN`: Your Telegram Bot Token.
        *   `ADMIN_IDS`: Telegram User IDs for bot administrators.
        *   TeamTalk server connection details (`HOST_NAME`, `PORT`, `USER_NAME`, `PASSWORD`).
        *   Web registration settings (if enabled, using variables like `WEB_APP_HOST`, `WEB_APP_PORT` which are now used by Uvicorn).
        *   The `FLASK_SECRET_KEY` (now removed/commented in `.env.example`) is not directly used by FastAPI for session management in the same way. Secure practices for any session/cookie management in FastAPI should be ensured if custom session logic is added.

6.  **Run the application using `uv`:**
    This command will run the `run.py` script within the `uv`-managed virtual environment. `run.py` now starts both the Telegram bot and the FastAPI web application (using Uvicorn).
    ```bash
    uv run python run.py
    ```
    The FastAPI application will be available at the host and port configured in your `.env` file (e.g., `http://127.0.0.1:5000`).

## Usage

*   **Telegram Bot:** Start a chat with your bot and send the `/start` command.
*   **Web Registration:** If enabled (`WEB_REGISTRATION_ENABLED=true` in `.env`), navigate to `http://<your_host>:<your_port>/register` (e.g., `http://127.0.0.1:5000/register`) in your web browser. The host and port are determined by `WEB_APP_HOST` and `WEB_APP_PORT` in your `.env` file.

## Testing

For instructions on how to run tests for the FastAPI application, please see `bot/fastapi_app/TESTING.md`.

## AI Contribution Note

Please be aware that approximately 60% of this project's codebase was generated with the assistance of Artificial Intelligence. While the code appears to function correctly and generally without bugs, you might encounter:

*   Comments in the code that seem like placeholders or notes from the AI (e.g., `# это оставлено здесь` - which translates to "this was left here").
*   Sections of code that may not be as human-readable or follow conventional best practices as code written entirely by a human developer.

We encourage contributions to improve code clarity and maintainability.

## Acknowledgements

This project wouldn't be possible without the contributions and inspiration from the following individuals and projects:

*   **[BlindMaster24](https://github.com/BlindMaster24):** For writing approximately 70% of this bot, including the initial framework and the addition of web registration. Their work on `py-talk-ex` is also foundational to this project.
*   **[gumerov-amir](https://github.com/gumerov-amir) and [m1maker](https://github.com/m1maker):** For their invaluable help in fixing a critical bug related to `.tt` file formatting, which ensured compatibility across different TeamTalk client versions.

And to the broader open-source community for the libraries and tools that make projects like this feasible.

## Contributing

Contributions are welcome! Please feel free to fork the repository, make your changes, and submit a pull request. If you find any bugs or have feature suggestions, please open an issue on the [GitHub Issues page](https://github.com/kirill-jjj/teamtalk_reg_system/issues).

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.