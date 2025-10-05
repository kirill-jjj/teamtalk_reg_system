"""This module handles FSM messages for the registration flow."""
import logging

from aiogram import Router

logger = logging.getLogger(__name__)

fsm_router = Router()
