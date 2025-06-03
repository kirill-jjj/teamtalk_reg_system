import sys
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
import httpx # For AsyncClient
from pathlib import Path

# Mock 'pytalk' and its submodules before other imports that might load it.
pytalk_mock = MagicMock()
pytalk_mock.message = MagicMock()
pytalk_mock.event = MagicMock()
pytalk_mock.exceptions = MagicMock()
pytalk_mock.user = MagicMock()
pytalk_mock.channel = MagicMock()
pytalk_mock.server = MagicMock()
pytalk_mock.enums = MagicMock()
sys.modules['pytalk'] = pytalk_mock
sys.modules['pytalk.message'] = pytalk_mock.message
sys.modules['pytalk.event'] = pytalk_mock.event
sys.modules['pytalk.exceptions'] = pytalk_mock.exceptions
sys.modules['pytalk.user'] = pytalk_mock.user
sys.modules['pytalk.channel'] = pytalk_mock.channel
sys.modules['pytalk.server'] = pytalk_mock.server
sys.modules['pytalk.enums'] = pytalk_mock.enums

import logging # Reverted

logger = logging.getLogger(__name__) # Reverted

from dotenv import load_dotenv
# Load .env file. This must happen before 'bot.core.config' is imported anywhere.
env_path = Path(".env")
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
    # print(f"Loaded environment variables from {env_path} for testing.") # Will be logged by logger later
else:
    # print(f"Warning: .env file not found at {env_path}. Config will rely on defaults or actual environment.") # Will be logged
    pass

# Import the FastAPI app instance and config module AFTER .env load and pytalk mock
from bot.fastapi_app.main import app
from bot.core import config as core_config_module # Import the module to monkeypatch
from bot.core.localization import get_translator # For test assertions


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="session", autouse=True) # Keep session scope for monkeypatching config once
def patch_config_for_session(monkeypatch): # Renamed, monkeypatch is function-scoped but its effects can be session-wide if applied to modules
    """Patches core_config module attributes for the entire test session."""
    logger.info("Monkeypatching core_config for test session...") # Removed await
    monkeypatch.setattr(core_config_module, "SERVER_ADDRESS", "test.teamtalk.server", raising=False)
    monkeypatch.setattr(core_config_module, "SERVER_COMMAND_PORT", 10334, raising=False)
    monkeypatch.setattr(core_config_module, "SERVER_TCP_PORT", 10333, raising=False)
    monkeypatch.setattr(core_config_module, "SERVER_UDP_PORT", 10333, raising=False)
    monkeypatch.setattr(core_config_module, "TT_ADMIN_USERNAME", "TestAdmin", raising=False)
    monkeypatch.setattr(core_config_module, "TT_ADMIN_PASSWORD", "TestAdminPassword", raising=False)
    monkeypatch.setattr(core_config_module, "CREATE_CLIENT_ZIP_ENABLED", True, raising=False)
    monkeypatch.setattr(core_config_module, "SERVER_NAME_DISPLAY", "TestServerDisplayFromPatch", raising=False)
    monkeypatch.setattr(core_config_module, "WEB_REGISTRATION_ENABLED", True, raising=False)
    monkeypatch.setattr(core_config_module, "GENERATED_FILE_TTL_SECONDS", 300, raising=False)
    # Ensure TEAMTALK_CLIENT_TEMPLATE_DIR is set if needed for base client zip creation part of startup
    # If it's not set, initial_fastapi_app_setup might use a dummy path.
    # For this test, let's assume it's not critical or will be handled by dummy path in config.


@pytest.fixture(scope="function") # Function scope for client to ensure fresh state and lifespan per test
# patch_config_for_session is now autouse=True, function-scoped, so it will run before this.
async def client(anyio_backend):
    """
    Provides an httpx.AsyncClient that manages the app's lifespan for each test.
    Also sets up app.state essentials like dummy bot and translator.
    """
    # Initialize app state elements normally set by run.py or that need to be fresh per test
    app.state.aiogram_bot_instance = MagicMock()
    # download_tokens and registered_ips are usually cleared by initial_fastapi_app_setup (lifespan startup)

    async with httpx.AsyncClient(app=app, base_url="http://testserver") as ac:
        # Lifespan "startup" event (initial_fastapi_app_setup) should have run here.
        # Now, set up the dummy translator after templates are loaded by startup.
        if hasattr(app.state, "templates") and app.state.templates:
            app.state.templates.env.globals['_'] = lambda text: text + " (translated)"
            app.state.templates.env.globals['get_translator'] = lambda lang_code: (lambda text: text + " (translated)")
            logger.info("Dummy translator '_' and get_translator added to template globals.") # Removed await
        else:
            logger.warning("Warning: app.state.templates not available after client startup. '_' not added.") # Removed await
        yield ac
    # Lifespan "shutdown" event should run here.

# --- Basic Tests (now async) ---
@pytest.mark.asyncio
async def test_read_main(client: httpx.AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "FastAPI is running"}

@pytest.mark.asyncio
async def test_set_language(client: httpx.AsyncClient):
    response = await client.get("/set_lang/ru")
    assert response.status_code == 200
    # httpx cookies are a bit different from TestClient's
    assert response.cookies.get("user_web_lang") == "ru"
    assert str(response.url).endswith("/register")

    response_en = await client.get("/set_lang/en")
    assert response_en.status_code == 200
    assert response_en.cookies.get("user_web_lang") == "en"

@pytest.mark.asyncio
async def test_register_page_get(client: httpx.AsyncClient): # Removed app_lifespan_manager
    # Test case when no lang cookie is set, should render choose_lang.html
    # app.state.cached_server_name is set during app startup via initial_fastapi_app_setup (triggered by client fixture),
    # which reads from core_config.SERVER_NAME (which is SERVER_NAME_DISPLAY due to patching)
    expected_server_name = "TestServerDisplayFromPatch" # From patch_config_for_session

    response_no_cookie = await client.get("/register")
    assert response_no_cookie.status_code == 200
    
    # Assertions for when no language cookie is set (renders choose_lang.html)
    # The context processor sets lang_code to DEFAULT_LANG_CODE ('en')
    # The template choose_lang.html uses `lang="{{ user_web_lang or 'en' }}"`
    assert '<html lang="en">' in response_no_cookie.text
    # Title uses the dummy translator from the client fixture
    assert "<title>Choose Language (translated)</title>" in response_no_cookie.text
    # Server name is passed to the template and should be present
    assert expected_server_name in response_no_cookie.text
    # Check for language selection links (also translated)
    assert "English 🇬🇧 (translated)" in response_no_cookie.text
    assert "Русский 🇷🇺 (translated)" in response_no_cookie.text
    assert 'href="/set_lang/en"' in response_no_cookie.text
    assert 'href="/set_lang/ru"' in response_no_cookie.text
    
    # Verify app.state.cached_server_name was indeed set as expected
    # This is more of a check on the test setup itself, ensuring the lifespan event ran.
    assert app.state.cached_server_name == expected_server_name

    # Test case when lang cookie is set
    response_with_cookie = await client.get("/register", cookies={"user_web_lang": "en"})
    assert response_with_cookie.status_code == 200

    # Assertions for when 'en' language cookie is set (renders register_unified.html)
    # Title structure: {{ _("TeamTalk Registration") }} - {{ server_name_from_env }}
    # Dummy translator adds " (translated)"
    assert f"<title>TeamTalk Registration (translated) - {expected_server_name}</title>" in response_with_cookie.text
    assert '<html lang="en">' in response_with_cookie.text
    
    # Check for form elements
    assert '<input type="text" id="username" name="username" required' in response_with_cookie.text
    assert '<input type="password" id="password" name="password" required' in response_with_cookie.text
    
    # Check form action (url_for('register_page_post') which is POST to /register)
    assert 'action="/register"' in response_with_cookie.text # Should resolve to the path for POST /register
    
    # Check that show_form was true by looking for key introductory text (translated)
    # Text: "{{ _("If you want to register on the server") }} "<strong>{{ server_name_from_env }}</strong>", {{ _("please fill out the form below.") }}"
    assert "please fill out the form below. (translated)" in response_with_cookie.text
    assert expected_server_name in response_with_cookie.text # Ensure server name is still visible


# --- Mocked Tests for POST /register (now async) ---
@pytest.mark.asyncio
@patch('bot.fastapi_app.routers.registration.teamtalk_client.check_username_exists', new_callable=AsyncMock)
@patch('bot.fastapi_app.routers.registration.teamtalk_client.perform_teamtalk_registration', new_callable=AsyncMock)
@patch('bot.fastapi_app.utils.generate_tt_file_content')
@patch('bot.fastapi_app.utils.create_client_zip_for_user')
@patch('bot.fastapi_app.utils.schedule_temp_file_deletion')
async def test_register_page_post_success(
    mock_schedule_deletion, mock_create_zip, mock_generate_tt,
    mock_perform_reg, mock_check_username,
    client: httpx.AsyncClient, tmp_path
):
    mock_check_username.return_value = False
    mock_perform_reg.return_value = True
    mock_generate_tt.return_value = "[TeamTalk5]...dummy content..."
    
    mock_generated_files_dir = tmp_path / "generated_files"
    mock_generated_files_dir.mkdir()
    mock_generated_zips_dir = tmp_path / "generated_zips"
    mock_generated_zips_dir.mkdir()

    dummy_zip_name_for_user = "testuser_TeamTalk_config.zip"
    dummy_zip_server_filename = "testuser_TestServerDisplayFromPatch_config_random.zip" # Matches logic in create_client_zip
    dummy_zip_path = mock_generated_zips_dir / dummy_zip_server_filename
    dummy_zip_path.write_text("dummy zip content")
    mock_create_zip.return_value = (dummy_zip_path, dummy_zip_name_for_user)

    with patch('bot.fastapi_app.utils.get_generated_files_path', return_value=mock_generated_files_dir), \
         patch('bot.fastapi_app.utils.get_generated_zips_path', return_value=mock_generated_zips_dir):
        
        response = await client.post("/register", data={"username": "testuser", "password": "testpassword"}, cookies={"user_web_lang":"en"})
        
        assert response.status_code == 200
        assert "Registration successful (translated)" in response.text
        assert "Download .tt file (translated)" in response.text
        
        mock_generate_tt.assert_called_once()
        assert mock_schedule_deletion.call_count >= 1
        
        if core_config_module.CREATE_CLIENT_ZIP_ENABLED:
            mock_create_zip.assert_called_once()
            assert mock_schedule_deletion.call_count >= 2
        else:
            mock_create_zip.assert_not_called()
        # httpx TestClient doesn't expose IP easily, so skipping IP check for now
        # assert "testclient" in app.state.registered_ips

@pytest.mark.asyncio
@patch('bot.fastapi_app.routers.registration.teamtalk_client.check_username_exists', new_callable=AsyncMock)
async def test_register_page_post_username_taken(mock_check_username, client: httpx.AsyncClient):
    mock_check_username.return_value = True
    response = await client.post("/register", data={"username": "existinguser", "password": "testpassword"}, cookies={"user_web_lang":"en"})
    assert response.status_code == 400
    assert "Username is already taken (translated)" in response.text

# --- Tests for Download Routes (now async) ---
@pytest.mark.asyncio
async def test_download_tt_file_valid_token(client: httpx.AsyncClient, tmp_path):
    token = "valid_tt_token_test"
    filename = "test_user.tt"
    file_content = "[TeamTalk5]...content..."
    
    mock_files_dir = tmp_path / "generated_files_for_download_tt"
    mock_files_dir.mkdir()
    dummy_file = mock_files_dir / filename
    dummy_file.write_text(file_content)

    app.state.download_tokens[token] = {"filename": filename, "type": "tt_config", "original_filename": filename}

    with patch('bot.fastapi_app.routers.registration.get_generated_files_path', return_value=mock_files_dir):
        response = await client.get(f"/download_tt/{token}")
        assert response.status_code == 200
        assert response.text == file_content
        assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'
    
    del app.state.download_tokens[token]

@pytest.mark.asyncio
async def test_download_tt_file_invalid_token(client: httpx.AsyncClient):
    response = await client.get("/download_tt/invalid_token_that_does_not_exist")
    assert response.status_code == 404
    json_response = response.json()
    assert "file_not_found_or_expired_error (translated)" in json_response["detail"]

# --- Test to check config loading and initial_fastapi_app_setup effects ---
@pytest.mark.asyncio
async def test_app_startup_and_config_check(client: httpx.AsyncClient): # Removed app_lifespan_manager, client ensures lifespan has run
    # Check if config values were correctly monkeypatched and loaded by config.py
    assert core_config_module.SERVER_ADDRESS == "test.teamtalk.server"
    assert core_config_module.SERVER_NAME_DISPLAY == "TestServerDisplayFromPatch"
    
    # Check if initial_fastapi_app_setup ran by checking one of its side effects on app.state
    assert hasattr(app.state, "cached_server_name")
    assert app.state.cached_server_name == "TestServerDisplayFromPatch" # Set by initial_fastapi_app_setup via core_config
    
    # Check if base_client_zip_path_on_disk was set by initial_fastapi_app_setup
    assert hasattr(app.state, "base_client_zip_path_on_disk")
    if core_config_module.TEAMTALK_CLIENT_TEMPLATE_DIR: # This check depends on whether template dir is set in dummy .env
        assert Path(app.state.base_client_zip_path_on_disk).name == "_base_client_template_fastapi.zip"
    else: # If not set, it might be a dummy path or raise error earlier
        assert Path(app.state.base_client_zip_path_on_disk).name == "dummy_base_client.zip"

    # Check templates and dummy translator
    assert hasattr(app.state, "templates")
    assert app.state.templates is not None
    assert '_' in app.state.templates.env.globals
    assert app.state.templates.env.globals['_']("test") == "test (translated)"

# TODO: Add tests for client ZIP download.

logger.info("Finished processing test_registration_routes.py") # Removed await
