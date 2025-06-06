import logging # Reverted to standard logging
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path # Added for base_dir
from bot.core.localization import get_translator, DEFAULT_LANG_CODE
from bot.core.config import FORCE_USER_LANG # Import FORCE_USER_LANG

import os # Added import for os module
logger = logging.getLogger(__name__) # Reverted

app = FastAPI(root_path=os.getenv("ROOT_PATH", "/")) # Added root_path using os.getenv

# Initialize application state variables
app.state.download_tokens = {}
app.state.registered_ips = set()

# --- Jinja2 Context Processor for i18n ---
def i18n_context_processor(request: Request):
    language_forced = False
    translator = None
    final_lang_code = DEFAULT_LANG_CODE # Initialize with default

    if FORCE_USER_LANG and FORCE_USER_LANG.strip():
        forced_lang_code = FORCE_USER_LANG.strip()
        _ = get_translator(forced_lang_code) # Changed _forced_lang_translator to _
        # Validate if the language is genuinely available
        original_string = "Username:" # A common string that should be translated
        translated_string = _(original_string) # Updated to _

        if translated_string != original_string:
            logger.debug(f"Forcing web language to '{forced_lang_code}' based on config.")
            translator = _ # Updated from _forced_lang_translator
            language_forced = True
            final_lang_code = forced_lang_code
        else:
            logger.warning(f"FORCE_USER_LANG was set to '{forced_lang_code}', but this language pack seems unavailable or incomplete for web. Falling back.")
            # Fallback logic will be handled by the else block or default initialization

    if not translator: # If not forced or forced language was invalid
        cookie_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
        translator = get_translator(cookie_lang_code)
        final_lang_code = cookie_lang_code
        language_forced = False # Ensure it's false if we fell back or it was never set

    return {"_": translator, "language_forced": language_forced, "current_lang": final_lang_code}

app.state.templates = Jinja2Templates(
    directory="bot/fastapi_app/templates",
    context_processors=[i18n_context_processor]
)
app.state.cached_server_name = "DefaultServerName (Not yet loaded)" # Placeholder
app.state.base_client_zip_path_on_disk = Path("dummy_base_client.zip") # Placeholder
# app.state.aiogram_bot_instance will be set by run.py before server starts

app.mount("/static", StaticFiles(directory="bot/fastapi_app/static"), name="static")

# --- Startup and Shutdown Event Handlers ---
from bot.core import config as core_config # Changed import
from bot.core.localization import refresh_translations
from bot.fastapi_app.utils import (
    get_generated_files_path, 
    get_generated_zips_path, 
    create_and_save_base_client_zip
)
import shutil # For rmtree

@app.on_event("startup")
async def initial_fastapi_app_setup(): # Removed app_instance parameter
    logger.info("Running FastAPI startup tasks...") # Removed await
    # 1. Set cached server name
    app.state.cached_server_name = core_config.SERVER_NAME # Use app from module scope, changed to SERVER_NAME

    # 2. Create/clean generated files/zips directories
    generated_files_dir = get_generated_files_path(app) # Use app from module scope
    generated_zips_dir = get_generated_zips_path(app)   # Use app from module scope

    # Clean directories first
    if generated_files_dir.exists():
        shutil.rmtree(generated_files_dir)
    generated_files_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Cleaned and created directory: {generated_files_dir}") # Removed await

    if generated_zips_dir.exists():
        shutil.rmtree(generated_zips_dir)
    generated_zips_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Cleaned and created directory: {generated_zips_dir}") # Removed await

    # 3. Create and save base client ZIP
    if core_config.TEAMTALK_CLIENT_TEMPLATE_DIR:
        base_zip_path = create_and_save_base_client_zip(app, core_config.TEAMTALK_CLIENT_TEMPLATE_DIR) # Use app
        if base_zip_path:
            app.state.base_client_zip_path_on_disk = base_zip_path # Use app
            logger.info(f"Base client ZIP created at: {base_zip_path}") # Removed await
        else:
            logger.error("Failed to create base client ZIP. Functionality requiring it may be affected.") # Removed await
            app.state.base_client_zip_path_on_disk = Path("dummy_base_client.zip") # Use app
    else:
        logger.info("TEAMTALK_CLIENT_TEMPLATE_DIR not configured. Skipping base client ZIP creation.") # Removed await
        app.state.base_client_zip_path_on_disk = Path("dummy_base_client.zip") # Use app

    # 4. Clear runtime state
    app.state.download_tokens.clear() # Use app
    app.state.registered_ips.clear()  # Use app
    logger.info("Cleared download tokens and registered IPs.") # Removed await

    # 5. Refresh translations
    try:
        refresh_translations()
        logger.info("Translations refreshed.") # Removed await
    except Exception as e:
        logger.error(f"Error refreshing translations: {e}", exc_info=True) # Removed await

    logger.info("FastAPI startup tasks completed.") # Removed await

@app.on_event("shutdown")
async def cleanup_fastapi_resources(): # Removed app_instance parameter
    logger.info("Running FastAPI shutdown tasks...") # Removed await
    # BackgroundTasks are fire-and-forget, so no specific cleanup needed for them here.
    # If other resources were acquired (e.g., database connections), they would be released here.
    # For now, this can be minimal.
    # Optional: Clean up generated files on shutdown if desired (for development)
    generated_files_dir = get_generated_files_path(app) # Example if app was needed
    if generated_files_dir.exists():
        shutil.rmtree(generated_files_dir)
    generated_zips_dir = get_generated_zips_path(app)
    if generated_zips_dir.exists():
        shutil.rmtree(generated_zips_dir)
    logger.info("Cleaned up generated files and zips directories on shutdown.") # Removed await
    logger.info("FastAPI shutdown tasks completed.") # Removed await


# Import and include registration router
from bot.fastapi_app.routers import registration # Moved import after event handlers for clarity
app.include_router(registration.router)

@app.get("/")
async def root():
    return {"message": "FastAPI is running"}
