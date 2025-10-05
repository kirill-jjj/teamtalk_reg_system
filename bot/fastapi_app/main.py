"""Main FastAPI application setup."""
import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)

app = FastAPI(root_path=os.getenv("ROOT_PATH", "/"))
