import logging
import secrets
from datetime import datetime, timedelta

from aiogram import types, Bot as AiogramBot, F, Router
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import config
from ...core.db.crud import create_deeplink_token
from ...core.localization import get_translator, get_admin_lang_code

logger = logging.getLogger(__name__)

router = Router()

@router.message(Command("generate"))
async def generate_deeplink_handler(message: types.Message, bot: AiogramBot, db_session: AsyncSession):
    # Check if the user is an admin
    # Ensure ADMIN_IDS in config contains integers or strings that can be cast to int
    # For this comparison, message.from_user.id is an int.
    # config.ADMIN_IDS stores them as strings if loaded from .env, cast them for comparison.
    admin_ids_int = []
    if config.ADMIN_IDS:
        for admin_id_str in config.ADMIN_IDS:
            try:
                admin_ids_int.append(int(admin_id_str))
            except ValueError:
                logger.warning(f"Invalid admin ID in config: {admin_id_str}. Skipping.")

    if message.from_user.id not in admin_ids_int:
        logger.warning(f"User {message.from_user.id} (not an admin) tried to use /generate.")
        # Optionally send a "permission denied" message if desired, or just return.
        # For now, just returning to avoid notifying non-admins about admin commands.
        return

    # Check if deeplink registration is enabled
    if not config.TELEGRAM_DEEPLINK_REGISTRATION_ENABLED:
        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)
        await message.reply(_("Deeplink registration is currently disabled in the configuration."))
        return

    try:
        token = secrets.token_urlsafe(32)
        # For simplicity, let's make token expiry a fixed value, e.g. 5 minutes
        # This could be made configurable via config.py if needed.
        token_expiry_minutes = 5
        expires_at = datetime.utcnow() + timedelta(minutes=token_expiry_minutes)
        acting_admin_id = message.from_user.id

        await create_deeplink_token(
            db_session,
            token_str=token,
            expires_at=expires_at,
            generated_by_admin_id=acting_admin_id
        )

        bot_info = await bot.get_me()
        bot_username = bot_info.username
        deeplink_url = f"https://t.me/{bot_username}?start={token}"

        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)

        # Ensure the deeplink URL itself is not misinterpreted by MarkdownV2
        # by escaping any special Markdown characters within it if necessary,
        # though for a URL, this is usually not an issue with backticks.
        # For simplicity, assuming deeplink_url is safe for direct insertion into MarkdownV2 backticks.
        # Escaping parentheses for MarkdownV2
        reply_text = _("Generated deeplink \\(expires in {num_minutes} minutes\\):\n`{deeplink}`").format(
            num_minutes=token_expiry_minutes,
            deeplink=deeplink_url
        )
        await message.reply(reply_text, parse_mode="MarkdownV2")
        logger.info(f"Admin {acting_admin_id} generated deeplink: {deeplink_url}")

    except Exception as e:
        logger.error(f"Error generating deeplink: {e}", exc_info=True)
        admin_lang = get_admin_lang_code()
        _ = get_translator(admin_lang)
        await message.reply(_("An error occurred while generating the deeplink."))


logger.info("Admin router initialized with /generate command handler.")
