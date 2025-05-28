# TeamTalk Registration System Bot

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![GitHub repository](https://img.shields.io/badge/GitHub-Repo-blue.svg)](https://github.com/kirill-jjj/teamtalk_reg_system)

A comprehensive bot solution for self-registration on TeamTalk 5 servers, featuring both a Telegram bot interface and an optional Flask-based web registration portal. This project aims to simplify user onboarding for TeamTalk communities.

## Why This Bot?

By default, TeamTalk server administrators are solely responsible for creating new user accounts. This can be a bottleneck for growing communities or for servers where administrators aren't always available. The TeamTalk Registration System Bot empowers users to register themselves, streamlining the process. This bot is distributed under the GPLv3 license, ensuring it remains free and open-source software.

It allows users to register:
*   Via a Telegram bot, with an optional admin approval step.
*   Via a web page (Flask-based), with IP-based registration limiting.

## Features

*   **Telegram Bot Registration:**
    *   User-friendly registration flow.
    *   Language selection (English/Russian).
    *   Optional admin approval for new registrations.
    *   Automatic generation and delivery of `.tt` connection files and quick-connect links.
*   **Web Registration (Flask):**
    *   Optional, can be enabled/disabled via configuration.
    *   Language selection on the web page (English/Russian).
    *   IP-based registration limiting (per Flask app session).
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

These instructions assume you have Python 3.11+ and `uv` (version 0.1.17+ or as recommended by `uv` for the `uv run` feature) installed globally. `uv` will automatically create and manage a virtual environment for this project.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/kirill-jjj/teamtalk_reg_system.git
    cd teamtalk_reg_system
    ```

2.  **Install dependencies and set up the environment using `uv`:**
    This command will create a virtual environment (if it doesn't exist) in a `.venv` folder within your project directory and install all dependencies from `requirements.txt`.
    ```bash
    uv sync
    ```

3.  **Configure the bot:**
    *   Rename `.env.example` to `.env`.
    *   Open the `.env` file with a text editor and fill in your specific details (see `.env.example` for required fields and descriptions). Key settings include:
        *   `TG_BOT_TOKEN`: Your Telegram Bot Token.
        *   `ADMIN_IDS`: Telegram User IDs for bot administrators.
        *   TeamTalk server connection details (`HOST_NAME`, `PORT`, `USER_NAME`, `PASSWORD`).
        *   Flask web registration settings (if enabled).
        *   **Important:** Change `FLASK_SECRET_KEY` to a strong, random value if using web registration.

4.  **Run the bot using `uv`:**
    This command will run the `run.py` script within the `uv`-managed virtual environment.
    ```bash
    uv run python run.py
    ```
    *(For Linux/macOS, if `run.py` has a shebang and is executable, `uv run ./run.py` might also work, but `uv run python run.py` is more universally compatible).*

## Usage

*   **Telegram Bot:** Start a chat with your bot and send the `/start` command.
*   **Web Registration:** If enabled, navigate to `http://<FLASK_HOST>:<FLASK_PORT>/register` (or your configured URL) in your web browser.

## Acknowledgements

This project wouldn't be possible without the contributions and inspiration from the following individuals and projects:

*   **[BlindMaster24](https://github.com/BlindMaster24):** For writing approximately 70% of this bot, including the initial framework and the addition of web registration. Their work on `py-talk-ex` is also foundational to this project.
*   **[gumerov-amir](https://github.com/gumerov-amir) and [m1maker](https://github.com/m1maker):** For their invaluable help in fixing a critical bug related to `.tt` file formatting, which ensured compatibility across different TeamTalk client versions.

And to the broader open-source community for the libraries and tools that make projects like this feasible.

## Contributing

Contributions are welcome! Please feel free to fork the repository, make your changes, and submit a pull request. If you find any bugs or have feature suggestions, please open an issue on the [GitHub Issues page](https://github.com/kirill-jjj/teamtalk_reg_system/issues).

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.