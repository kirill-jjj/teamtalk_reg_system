# Testing the FastAPI Registration Application

This document provides instructions on how to run the tests for the FastAPI registration application.

## Prerequisites

Make sure you are in the root directory of the project where `pyproject.toml` is located.
It's also assumed you have `uv` installed. If not, refer to the main `README.md` for `uv` installation instructions.

## Installation of Dependencies

1.  **Create/update virtual environment and install dependencies using `uv`:**
    Navigate to the root of the project. The following command will create a virtual environment (e.g., in `.venv`) if one doesn't exist, and then synchronize the environment with all necessary dependencies (including development dependencies) specified in `pyproject.toml`.
    ```bash
    uv sync --dev
    ```
    This ensures your environment has all packages required for running the application and its tests (like `pytest`, `pytest-asyncio`, and `httpx`).

2.  **Activate the virtual environment:**
    If `uv` didn't automatically activate the environment, or if you open a new terminal, activate it manually:
    *   Linux/macOS: `source .venv/bin/activate`
    *   Windows: `.\.venv\Scripts\activate`
    (The virtual environment directory might be named differently if customized via `uv` or system configuration).

## Running Tests

1.  **Navigate to the root directory of the project** (if you aren't already there).

2.  **Run Pytest:**
    To run all tests located in the `bot/fastapi_app/tests/` directory, execute the following command:
    ```bash
    pytest bot/fastapi_app/tests/
    ```
    Pytest will automatically discover and run the tests in the specified directory.

    You can also run tests with more verbosity:
    ```bash
    pytest -vv bot/fastapi_app/tests/
    ```

## Mocking Strategy

The tests in `test_registration_routes.py` employ several mocking techniques:

*   **`@pytest.fixture(scope="session", autouse=True)`:** A session-scoped autouse fixture named `setup_test_app_state` in `test_registration_routes.py` is used to prepare the application state (`app.state`) with necessary mocks (like a mock Aiogram bot instance, cached server name, etc.) before tests run. This ensures that the tests operate in a controlled environment without relying on the full `run.py` sequence or external services.
*   **`@patch` and `@patch.object` (from `unittest.mock`):** These decorators are used to replace functions and methods with `MagicMock` or `AsyncMock` instances. This is crucial for:
    *   Isolating tests from external services like the TeamTalk server (e.g., `teamtalk_client.check_username_exists`, `teamtalk_client.perform_teamtalk_registration`).
    *   Controlling the behavior of utility functions that interact with the file system (e.g., `create_client_zip_for_user`, `generate_tt_file_content`) or schedule background tasks (`schedule_temp_file_deletion`).
    *   Mocking path generation functions (`get_generated_files_path`, `get_generated_zips_path`) to use temporary directories (`tmp_path` fixture provided by pytest) during tests, preventing tests from writing to or deleting from the actual generated file directories.
*   **`AsyncMock`:** Used for mocking asynchronous functions (`async def`).
*   **`tmp_path` pytest fixture:** Used to create temporary directories for tests that involve file system operations, ensuring that tests do not leave behind artifacts and do not interfere with each other or the actual application data.

When writing new tests, especially for route handlers that have external dependencies or side effects:
*   Identify all external calls (to other modules, services, file system).
*   Use `@patch` (or `pytest-mock`'s `mocker` fixture) to mock these dependencies within the scope of your test function. Remember to patch where the object is *looked up*, not necessarily where it's defined. For instance, if a function in `routers.registration` calls a function from `utils`, you'd typically patch `bot.fastapi_app.routers.registration.the_function_from_utils`.
*   Provide appropriate return values or side effects for your mocks to simulate different scenarios (e.g., success, failure, specific data returned).
*   Use fixtures for common setup logic (like initializing the `TestClient` or preparing mock data).
