import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.templating import Jinja2Templates

from bot.core.config import settings
from bot.core.localization import (
    DEFAULT_LANG_CODE,
    get_available_languages_for_display,
    get_translator,
)

logger = logging.getLogger(__name__)

app = FastAPI(root_path=os.getenv("ROOT_PATH", "/"))


# --- Jinja2 Context Processor for i18n ---
def i18n_context_processor(request: Request):
    language_forced = False
    translator = None
    final_lang_code = DEFAULT_LANG_CODE  # Initialize with default

    if settings.force_user_lang:
        forced_lang_code = settings.force_user_lang
        _ = get_translator(forced_lang_code)
        # Validate if the language is genuinely available
        original_string = "Username:"  # A common string that should be translated
        translated_string = _(original_string)

        if translated_string != original_string:
            logger.debug(f"Forcing web language to '{forced_lang_code}' based on config.")
            translator = _
            language_forced = True
            final_lang_code = forced_lang_code
        else:
            logger.warning(
                f"FORCE_USER_LANG was set to '{forced_lang_code}', but this language pack seems unavailable or incomplete for web. Falling back."
            )
            # Fallback logic will be handled by the else block or default initialization

    if not translator:  # If not forced or forced language was invalid
        cookie_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
        translator = get_translator(cookie_lang_code)
        final_lang_code = cookie_lang_code
        language_forced = False  # Ensure it's false if we fell back or it was never set

    return {
        "_": translator,
        "language_forced": language_forced,
        "current_lang": final_lang_code,
    }


app.state.templates = Jinja2Templates(
    directory="bot/fastapi_app/templates", context_processors=[i18n_context_processor]
)
app.state.cached_server_name = "DefaultServerName (Not yet loaded)"
app.state.base_client_zip_path_on_disk = Path("dummy_base_client.zip")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
    translator = get_translator(user_lang_code)
    available_languages = get_available_languages_for_display()

    # Format Pydantic's validation errors into a user-friendly string
    error_messages = []
    for error in exc.errors():
        # error['loc'] is a tuple like ('body', 'username')
        field = error["loc"][-1]
        message = error["msg"]
        error_messages.append(f"{field.capitalize()}: {message}")

    return app.state.templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "title": translator("TeamTalk Registration"),
            "message": "\n".join(error_messages),
            "show_form": True,
            "current_lang": user_lang_code,
            "server_name_from_env": app.state.cached_server_name,
            "available_languages": available_languages,
        },
        status_code=400,
    )


# --- Startup and Shutdown Event Handlers ---
import shutil

from bot.core.localization import refresh_translations
from bot.fastapi_app.utils import (
    create_and_save_base_client_zip,
    get_generated_files_path,
    get_generated_zips_path,
)


@app.on_event("startup")
async def initial_fastapi_app_setup():
    logger.info("Running FastAPI startup tasks...")
    # 1. Set cached server name
    app.state.cached_server_name = settings.server_name

    # 2. Create/clean generated files/zips directories
    generated_files_dir = get_generated_files_path(app)
    generated_zips_dir = get_generated_zips_path(app)

    # Clean directories first
    if generated_files_dir.exists():
        shutil.rmtree(generated_files_dir)
    generated_files_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Cleaned and created directory: {generated_files_dir}")

    if generated_zips_dir.exists():
        shutil.rmtree(generated_zips_dir)
    generated_zips_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Cleaned and created directory: {generated_zips_dir}")

    # 3. Create and save base client ZIP
    if settings.teamtalk_client_template_dir:
        base_zip_path = create_and_save_base_client_zip(
            app, settings.teamtalk_client_template_dir
        )
        if base_zip_path:
            app.state.base_client_zip_path_on_disk = base_zip_path
            logger.info(f"Base client ZIP created at: {base_zip_path}")
        else:
            logger.error(
                "Failed to create base client ZIP. Functionality requiring it may be affected."
            )
            app.state.base_client_zip_path_on_disk = Path("dummy_base_client.zip")
    else:
        logger.info(
            "TEAMTALK_CLIENT_TEMPLATE_DIR not configured. Skipping base client ZIP creation."
        )
        app.state.base_client_zip_path_on_disk = Path("dummy_base_client.zip")

    # 4. Clear runtime state
    logger.info("Download tokens and registered IPs are now DB-managed.")

    # 5. Refresh translations
    try:
        refresh_translations()
        logger.info("Translations refreshed.")
    except Exception as e:
        logger.error(f"Error refreshing translations: {e}", exc_info=True)

    logger.info("FastAPI startup tasks completed.")


@app.on_event("shutdown")
async def cleanup_fastapi_resources():
    logger.info("Running FastAPI shutdown tasks...")
    # BackgroundTasks are fire-and-forget, so no specific cleanup needed for them here.
    # If other resources were acquired (e.g., database connections), they would be released here.
    # For now, this can be minimal.
    # Optional: Clean up generated files on shutdown if desired (for development)
    generated_files_dir = get_generated_files_path(app)
    if generated_files_dir.exists():
        shutil.rmtree(generated_files_dir)
    generated_zips_dir = get_generated_zips_path(app)
    if generated_zips_dir.exists():
        shutil.rmtree(generated_zips_dir)
    logger.info("Cleaned up generated files and zips directories on shutdown.")
    logger.info("FastAPI shutdown tasks completed.")


# Import and include registration router
from bot.fastapi_app.routers import registration

app.include_router(registration.router)


@app.get("/")
async def root():
    return {"message": "FastAPI is running"}