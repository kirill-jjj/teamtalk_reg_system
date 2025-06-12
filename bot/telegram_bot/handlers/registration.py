import logging

from aiogram import Router

# Import routers from the new handler files
from .reg_command_handlers import command_router
from .reg_callback_handlers import callback_router
from .reg_fsm_message_handlers import fsm_router

logger = logging.getLogger(__name__)

# The main router for the registration functionality
router = Router(name=__name__) # Using module name for the router name

# Include the routers from the individual handler files
router.include_router(command_router)
router.include_router(callback_router)
router.include_router(fsm_router)

logger.info("Main registration router configured with sub-routers from reg_command_handlers, reg_callback_handlers, and reg_fsm_message_handlers.")
