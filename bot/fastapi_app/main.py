import logging
import os
from pathlib import Path
import shutil

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.templating import Jinja2Templates

from bot.core.config import settings
from bot.core.localization import (
    DEFAULT_LANG_CODE,
    get_available_languages_for_display,
    get_translator,
    refresh_translations,
)
from bot.fastapi_app.utils import (
    create_and_save_base_client_zip,
    get_generated_files_path,
    get_generated_zips_path,
)
from bot.fastapi_app.routers import registration

logger = logging.getLogger(__name__)

app = FastAPI(root_path=os.getenv("ROOT_PATH", "/"))
