"""Main FastAPI application setup."""
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from bot.core.config import settings

logger = logging.getLogger(__name__)

app = FastAPI(root_path=os.getenv("ROOT_PATH", "/"))

# Configure Jinja2Templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
app.state.templates = templates
app.state.cached_server_name = settings.server_name
