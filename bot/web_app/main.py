import logging
import os
import asyncio
from flask import Flask
from typing import TYPE_CHECKING

from ..core import config as core_config # App-wide config
from .routes import registration as reg_routes # Import the blueprint

if TYPE_CHECKING:
    from aiogram import Bot as AiogramBot


logger = logging.getLogger(__name__)

def create_flask_app(aiogram_bot_instance: 'AiogramBot', event_loop: asyncio.AbstractEventLoop) -> Flask:
    """
    Creates and configures the Flask application instance.
    """
    app = Flask(__name__)
    app.secret_key = core_config.FLASK_SECRET_KEY # For session management

    # Pass the event loop to the routes module for async tasks
    reg_routes.set_async_loop(event_loop)
    # Pass the Aiogram bot instance for admin notifications from Flask routes
    reg_routes.set_aiogram_bot_instance(aiogram_bot_instance)


    # Perform initial setup like creating base ZIP (if configured)
    with app.app_context(): # Need app context for operations like get_generated_zips_path
        reg_routes.initial_flask_app_setup(app)

    app.register_blueprint(reg_routes.flask_bp)
    logger.info("Flask application created and blueprint registered.")
    return app

def run_flask_app(app: Flask):
    """
    Runs the Flask application.
    This function is intended to be run in a separate thread from the main asyncio loop.
    """
    ssl_context_val = None
    protocol_to_log = "http"

    if core_config.FLASK_SSL_ENABLED:
        if core_config.FLASK_SSL_CERT_PATH and core_config.FLASK_SSL_KEY_PATH and \
           os.path.exists(core_config.FLASK_SSL_CERT_PATH) and os.path.exists(core_config.FLASK_SSL_KEY_PATH):
            ssl_context_val = (core_config.FLASK_SSL_CERT_PATH, core_config.FLASK_SSL_KEY_PATH)
            protocol_to_log = "https"
            logger.info(f"Flask SSL enabled. Cert: {core_config.FLASK_SSL_CERT_PATH}, Key: {core_config.FLASK_SSL_KEY_PATH}")
        else:
            logger.warning("FLASK_SSL_ENABLED is true, but SSL cert/key paths are invalid or files missing. Running Flask without SSL.")
            # Fallback to HTTP if SSL config is bad but SSL was enabled.

    logger.info(f"Starting Flask server on {protocol_to_log}://{core_config.FLASK_HOST}:{core_config.FLASK_PORT}")
    try:
        # Werkzeug is the default dev server. For production, use Gunicorn or similar.
        # debug=False is important for production/semi-production.
        app.run(
            host=core_config.FLASK_HOST,
            port=core_config.FLASK_PORT,
            debug=False, # Set to True for development ONLY
            ssl_context=ssl_context_val,
            threaded=True # Werkzeug's threaded mode can handle multiple requests
        )
    except Exception as e:
        logger.exception(f"Flask app run failed: {e}")
    finally:
        # Cleanup timers when Flask app stops (e.g., on Ctrl+C if run directly, or when thread terminates)
        with app.app_context(): # Ensure app context for cleanup
             reg_routes.cleanup_flask_resources()
        logger.info("Flask application has shut down.")
