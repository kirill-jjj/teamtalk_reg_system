# Project Development Guide & Coding Style

## 1. Overview

*   **Brief Project Description:**
    This project is a multi-interface bot designed to facilitate user registration for a TeamTalk 5 server. It provides both a Telegram bot interface and a FastAPI-based web application for users to create new TeamTalk accounts. The system also includes administrative features for managing registrations.

*   **Core Technologies:**
    *   Python 3.x
    *   Aiogram (Telegram Bot Framework)
    *   FastAPI (Web Framework)
    *   Pytalk (py-talk-ex) (TeamTalk Client Library)
    *   SQLAlchemy (ORM for database interaction) with aiosqlite (async SQLite driver)
    *   Babel (Internationalization/Localization)
    *   Uvicorn (ASGI Server)
    *   Dotenv (Environment variable management)

## 2. Coding Style and Conventions

*   **Formatting:**
    *   Adherence to **PEP 8** is encouraged.
    *   **Indentation:** 4 spaces per indentation level.
    *   Line length should generally be kept within reasonable limits (e.g., 79-99 characters) for readability, though some flexibility is allowed for long strings or complex list/dictionary definitions.

*   **Naming Conventions:**
    *   **Modules:** `snake_case.py` (e.g., `teamtalk_client.py`, `config.py`).
    *   **Packages:** `snake_case` (e.g., `telegram_bot`, `fastapi_app`).
    *   **Classes:** `PascalCase` (e.g., `TelegramRegistration`, `RegistrationStates`).
    *   **Functions & Methods:** `snake_case()` for synchronous code, `async_snake_case()` for asynchronous code (e.g., `get_translator()`, `perform_teamtalk_registration()`).
    *   **Variables:** `snake_case` (e.g., `user_name`, `active_session`).
    *   **Constants:** `UPPER_SNAKE_CASE` (e.g., `TG_BOT_TOKEN`, `DEFAULT_LANG_CODE`).

*   **Comments:**
    *   **Docstrings:** Public modules, classes, functions, and methods should have descriptive docstrings (PEP 257). Docstrings should explain the purpose, arguments, and return values (if any). Multi-line docstrings are preferred for complex functions.
    *   **Inline Comments:** Use inline comments (`# comment`) to explain non-obvious logic, complex sections, or important decisions.
    *   **Language:** All comments and docstrings should be written in **English** for consistency and broader understanding.

*   **Logging:**
    *   **Setup:** Centralized logging configuration is done in `run.py` using `logging.basicConfig()`. Module-specific loggers are obtained via `logger = logging.getLogger(__name__)`.
    *   **Levels:** Use appropriate log levels:
        *   `DEBUG`: For detailed diagnostic information useful during development.
        *   `INFO`: For general operational messages, status updates, and successful events.
        *   `WARNING`: For potential issues, recoverable errors, or unusual situations.
        *   `ERROR`: For errors that prevent a specific operation from completing but don't halt the entire application.
        *   `EXCEPTION` (via `logger.exception()`): For errors caught in `try-except` blocks where the stack trace is valuable.
    *   **Formatting:** Log messages should be clear, concise, and provide context. The format defined in `run.py` (`%(asctime)s - %(name)s - %(levelname)s - %(message)s`) is standard.

*   **Error Handling:**
    *   Catch specific exceptions where possible (e.g., `ValueError`, `SQLAlchemyIntegrityError`).
    *   Use general `except Exception as e:` sparingly, primarily as a fallback or in top-level handlers.
    *   Employ `try-except-finally` blocks for resource cleanup (e.g., closing sessions, releasing locks).
    *   Log errors appropriately, including stack traces for unexpected issues (`logger.exception()`).
    *   Provide user-friendly error messages in the UI (bot or web).

*   **Imports:**
    *   **Grouping:** Imports should be grouped in the following order (PEP 8):
        1.  Standard library imports.
        2.  Related third-party imports.
        3.  Local application/library specific imports.
    *   **Order:** Within each group, imports should generally be alphabetized.
    *   Absolute imports are preferred over relative imports where clarity is maintained.
    *   Use `from typing import ...` for type hints. Conditional imports for type checking (`if TYPE_CHECKING:`) are used where necessary.

## 3. Project Architecture

*   **Main Components and Interactions:**
    *   **`run.py`:** The main entry point. Initializes and orchestrates all other components using `asyncio`. It starts the Telegram bot, Pytalk client, and FastAPI web server.
    *   **`core/` Package:** Contains shared, foundational modules:
        *   `config.py`: Manages all application configuration.
        *   `database.py`: Handles database connections, schema, and operations.
        *   `localization.py`: Manages internationalization and translations.
        *   `teamtalk_client.py`: Encapsulates all interactions with the TeamTalk server via the `pytalk` library.
    *   **`telegram_bot/` Package:** Manages the Telegram bot interface.
        *   `main.py`: Initializes the Aiogram dispatcher, registers handlers, and sets up Pytalk event listeners relevant to bot operations.
        *   `handlers/`: Contains handler logic for different commands and conversation states.
        *   `states.py`: Defines FSM states for managing conversation flows.
    *   **`fastapi_app/` Package:** Manages the web interface.
        *   `main.py`: Initializes the FastAPI application, sets up event handlers (startup/shutdown), Jinja2 templating, and static files.
        *   `routers/`: Contains route definitions for different parts of the web application (e.g., `registration.py`).
        *   `templates/`: HTML templates for the web UI.
        *   `static/`: Static assets (CSS, JS, images).
    *   **Interactions:** The `telegram_bot` and `fastapi_app` components utilize services from the `core/` package. `run.py` ensures these components run concurrently and can communicate where necessary (e.g., passing the bot instance to FastAPI for admin notifications).

*   **Configuration Management:**
    *   Managed by `bot/core/config.py`.
    *   Uses `python-dotenv` to load settings from a `.env` file at the project root.
    *   Environment variables are parsed, validated, and converted to Python types.
    *   Provides default values for optional settings.
    *   Critical configuration errors lead to application exit.

*   **Database Interaction:**
    *   **ORM:** SQLAlchemy is used as the Object-Relational Mapper.
    *   **Driver:** `aiosqlite` provides asynchronous connectivity to SQLite.
    *   **Sessions:** Asynchronous sessions are managed via `create_async_engine` and `async_sessionmaker`. Operations are performed within `async with AsyncSessionLocal() as session:` blocks.
    *   **Schema:** The database schema (tables, columns) is defined using SQLAlchemy's declarative mapping (e.g., `TelegramRegistration` class in `database.py`). `Base.metadata.create_all(bind=engine)` is used for initial schema creation.

*   **Localization Strategy:**
    *   Uses the `babel` library.
    *   Translations are stored in `.po` files, compiled to `.mo` files, and organized in `locales/[lang_code]/LC_MESSAGES/`.
    *   `bot/core/localization.py` discovers available languages, loads translations, and provides a `get_translator(lang_code)` function.
    *   This function returns a `gettext`-like callable for retrieving translated strings.
    *   Supports forced language via configuration and language selection via cookies (web) or user choice (Telegram).

*   **Asynchronous Programming:**
    *   The entire application is built around `asyncio`.
    *   `async` and `await` are used extensively for I/O-bound operations, ensuring non-blocking execution. This includes Telegram API calls, web requests, TeamTalk server interactions, and database operations.

*   **Key Design Patterns:**
    *   **State Machine:** Used in the Telegram bot (`aiogram.fsm`) to manage multi-step registration flows.
    *   **Router/Dispatcher:** FastAPI (`APIRouter`) and Aiogram (`Dispatcher`, `Router`) map incoming requests/messages to appropriate handler functions.
    *   **Observer (Event Handling):** The Pytalk client uses event decorators (`@pytalk_bot.event`) to allow other parts of the system (e.g., `telegram_bot/main.py`) to react to TeamTalk server events.
    *   **Centralized Configuration:** `bot/core/config.py` acts as a single source of truth for all settings.
    *   **Singleton (Implicit):** Core services like the Pytalk client instance, database engine, and loaded translations are initialized once and shared across the application.
    *   **Background Tasks (FastAPI):** Used for operations that should not block the HTTP response (e.g., deleting temporary files).
    *   **Dependency Injection (FastAPI):** FastAPI automatically injects dependencies like `Request`, `Form` data, and `BackgroundTasks` into route handlers.

## 4. Libraries and Frameworks

*   **Aiogram:**
    *   Used for building the Telegram bot.
    *   Key patterns: `Dispatcher` and `Router` for handling updates, `FSMContext` for state management, `types` for Telegram objects (Message, CallbackQuery), `Bot` class for API interactions.
*   **Pytalk (py-talk-ex):**
    *   Used for interacting with the TeamTalk 5 server.
    *   Key patterns: `TeamTalkBot` instance, `ServerInfo` for connection details, event-driven architecture (`@pytalk_bot.event`), methods for user account management (e.g., `create_user_account`, `list_user_accounts`).
*   **FastAPI:**
    *   Used for building the asynchronous web application.
    *   Key patterns: `FastAPI` app instance, `APIRouter` for modular routing, Pydantic for data validation (implicitly via form data), Jinja2 for templating, `Request` and `Response` objects, dependency injection.
*   **Uvicorn:**
    *   The ASGI server used to run the FastAPI application. Configuration is handled in `run.py`.
*   **SQLAlchemy:**
    *   Used as an ORM for database interactions.
    *   Key patterns: `DeclarativeBase` for model definitions, `async_engine` and `async_sessionmaker` for asynchronous operations, `Column` types, query API (though direct object manipulation is common for simple cases).
*   **Babel:**
    *   Used for internationalization and localization.
    *   Key patterns: `Translations.load()` for loading `.mo` files, `gettext()` method for retrieving translated strings. `.po` file format for defining translations.

## 5. Development Patterns

*   **Adding Telegram Handlers:**
    *   Define handler functions (usually `async`) in a relevant file within `bot/telegram_bot/handlers/`.
    *   Use decorators from an Aiogram `Router` instance (e.g., `@router.message(Command("mycommand"))`, `@router.callback_query(F.data == "my_callback")`).
    *   For stateful conversations, define states in `RegistrationStates` (or a similar `StatesGroup`) and use `state: FSMContext` in handlers to manage state.
    *   Register the router with the main dispatcher in `bot/telegram_bot/main.py`.
*   **Adding FastAPI Routes:**
    *   Define route functions (usually `async`) in a relevant file within `bot/fastapi_app/routers/`.
    *   Use decorators from an `APIRouter` instance (e.g., `@router.get("/path")`, `@router.post("/path")`).
    *   Use FastAPI's dependency injection for request data, forms, etc.
    *   Return `TemplateResponse` for HTML pages, or other FastAPI response types (e.g., `FileResponse`, `RedirectResponse`).
    *   Include the router in the main FastAPI app instance in `bot/fastapi_app/main.py`.
*   **Database Migrations (Current Approach):**
    *   The current setup relies on `Base.metadata.create_all(engine)` for initial schema creation.
    *   For schema changes after initial creation, manual SQL alterations or a more robust migration tool (like Alembic, if integrated) would be required. The project does not currently specify an automated migration tool beyond initial creation.
*   **Testing (Current Approach):**
    *   The `run.py` script includes a `--test-run` argument that allows the application to initialize, perform startup tasks, and then exit. This can catch basic configuration and initialization errors.
    *   No dedicated unit or integration testing framework (like `pytest` or `unittest`) is explicitly mentioned or configured in the provided file structure. Adding such tests would be a significant improvement for maintainability.
