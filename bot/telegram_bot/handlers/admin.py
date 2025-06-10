import logging

from aiogram import Router

logger = logging.getLogger(__name__)

router = Router()

# Future admin command handlers can be added here using @router.message(...)
# For example:
# from aiogram.filters import Command
# @router.message(Command("admin_action"))
# async def some_admin_command(message: types.Message):
#     ...

logger.info("Admin router initialized.")