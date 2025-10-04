import asyncio
from asyncio import Task
import logging
import time

from pytalk import Channel as TeamTalkChannel
from pytalk import TeamTalkInstance, UserAccount, UserType, user
from pytalk.message import Message
from pytalk.server import Server as TeamTalkServer

from bot.core.config import settings
from bot.core.db.crud import add_banned_user, get_telegram_id_by_teamtalk_username
from bot.core.db.session import AsyncSessionLocal

from ..core.localization import get_admin_lang_code, get_translator
from .connection import force_restart_instance_on_event, pytalk_bot

logger = logging.getLogger(__name__)

# A cache to hold usernames that were recently deleted.
# Maps username -> (timestamp, notification_task)
recently_deleted_users: dict[str, tuple[float, Task]] = {}
DELETION_WINDOW_SECONDS = 2  # 2-second window to detect a quick delete/create as an update.


async def _send_delayed_removal_notification(username: str):
    """Waits for a defined period and then sends a removal notification.
    This task is intended to be cancelled if the user is re-created quickly.
    """
    try:
        await asyncio.sleep(DELETION_WINDOW_SECONDS)
        # If we reach here, the task was not cancelled.
        logger.info("Sending delayed removal notification for '%s' as no re-creation was detected.", username)

        # Clean up the cache entry for this user
        recently_deleted_users.pop(username, None)

        aiogram_bot = pytalk_bot.aiogram_bot_ref
        if not aiogram_bot or not settings.admin_ids:
            logger.error("_send_delayed_removal_notification: Aiogram bot or ADMIN_IDS not configured.")
            return

        _ = get_translator(get_admin_lang_code())

        message_to_send = _("TeamTalk: User account '{username}' has been REMOVED.").format(username=username)

        for admin_id in settings.admin_ids:
            try:
                chat_id_int = int(admin_id)
                await aiogram_bot.send_message(chat_id=chat_id_int, text=message_to_send)
            except Exception as e:
                logger.error("Failed to send delayed removal notification to admin %s for user '%s': %s", admin_id, username, e)

    except asyncio.CancelledError:
        # This is expected if the user is re-created quickly.
        logger.info("Delayed removal notification for '%s' was cancelled due to re-creation.", username)
        # The cache cleanup is handled by the 'on_user_account_new' event which caused the cancellation.
    finally:
        if username in recently_deleted_users:
            # This is a safeguard. The entry should be removed either by the successful run of this task
            # or by the 'on_user_account_new' task that cancels it.
            # If it's still here, it might be a logic gap, so we log it.
            logger.warning("Cache entry for '%s' still existed in finally block of removal task.", username)
            del recently_deleted_users[username]


# Helper function for banning
async def _handle_banning_on_tt_account_removal(tt_username: str, server_host_info: str):
    logger.info("Attempting to process ban for TeamTalk user '%s' deleted from server '%s'.", tt_username, server_host_info)
    async with AsyncSessionLocal() as session:
        try:
            telegram_id = await get_telegram_id_by_teamtalk_username(session, tt_username)
            if telegram_id:
                logger.info("Found Telegram ID %s for TeamTalk user '%s'. Proceeding to ban.", telegram_id, tt_username)
                await add_banned_user(
                    db_session=session,
                    telegram_id=telegram_id,
                    teamtalk_username=tt_username,
                    reason=f"Account deleted from TeamTalk server: {server_host_info}"
                )
                logger.info("Successfully processed ban for Telegram ID %s (TeamTalk: %s).", telegram_id, tt_username)
            else:
                logger.warning("No Telegram ID found for TeamTalk user '%s'. Cannot add to bot's ban list.", tt_username)
        except Exception as e:
            logger.error("Error during automatic banning process for TeamTalk user '%s': %s", tt_username, e, exc_info=True)


def get_admin_users(teamtalk_instance: TeamTalkInstance) -> list[user]:
    """Retrieves a list of admin users from the server.
    """
    admin_users: list[user] = []
    if not teamtalk_instance or not hasattr(teamtalk_instance, 'server'):
        logger.warning("get_admin_users: Invalid teamtalk_instance or server attribute missing.")
        return admin_users

    try:
        all_users: list[user] = teamtalk_instance.server.get_users()
    except Exception as e:
        logger.error("get_admin_users: Error getting users from server: %s", e)
        return admin_users

    for user in all_users:
        try:
            if hasattr(user, 'user_type') and user.user_type == UserType.ADMIN:
                admin_users.append(user)
        except Exception as e:
            logger.error("get_admin_users: Error processing user %s: %s", getattr(user, 'id', 'UnknownID'), e)
    return admin_users

@pytalk_bot.event
async def on_ready():
    logger.info("PyTalk Bot is ready (on_ready event).")

@pytalk_bot.event
async def on_my_login(server: TeamTalkServer):
    host_info = server.info.host if server and hasattr(server, 'info') and server.info else 'Unknown Server'
    logger.info("Successfully logged in to server: %s (on_my_login event).", host_info)
    tt_instance = getattr(server, 'teamtalk_instance', None)
    if not tt_instance:
        for inst in pytalk_bot.teamtalks:
            if inst.server is server:
                tt_instance = inst
                break
    if tt_instance:
        try:
            bot_user_id = tt_instance.getMyUserID()
            bot_user_account = tt_instance.getMyUserAccount()
            tt_instance.cached_my_user_id = bot_user_id
            tt_instance.cached_my_user_account = bot_user_account
            bot_username = bot_user_account.szUsername
            if isinstance(bot_username, bytes):
                bot_username = bot_username.decode('utf-8')
            logger.info("Bot's info cached on login. UserID: %s, Username: '%s'", bot_user_id, bot_username)
        except Exception as e:
            logger.error("Failed to cache bot user info on login: %s", e, exc_info=True)
            tt_instance.cached_my_user_id = None
            tt_instance.cached_my_user_account = None

@pytalk_bot.event
async def on_message(message: Message):
    logger.info("Received message (on_message event): Type: %s, From ID: %s, Content: '%s...'", type(message).__name__, message.from_id, message.content[:50])

@pytalk_bot.event
async def on_error(event_name: str, *args, **kwargs):
    logger.error("Error in event handler '%s'. Args: %s, Kwargs: %s", event_name, args, kwargs, exc_info=True)

@pytalk_bot.event
async def on_my_connect(server: TeamTalkServer):
   host_info = server.info.host if server and hasattr(server, 'info') and server.info else 'Unknown Server'
   logger.info("Successfully connected to server: %s (on_my_connect event)", host_info)

@pytalk_bot.event
async def on_my_disconnect(server: TeamTalkServer):
    host = server.info.host if server and hasattr(server, 'info') and server.info else 'Unknown Server'
    logger.info("Bot gracefully disconnected from server: %s (on_my_disconnect event).", host)

@pytalk_bot.event
async def on_my_connection_lost(server: TeamTalkServer):
    host = "Unknown Server"
    tt_instance = getattr(server, 'teamtalk_instance', None)
    if tt_instance and hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
        host = tt_instance.server_info_tuple[0]
    elif server and hasattr(server, 'info') and server.info:
        host = server.info.host
    logger.warning("EVENT: on_my_connection_lost - Connection lost from server %s. Triggering forceful instance restart.", host)
    if tt_instance and hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
        asyncio.create_task(force_restart_instance_on_event(*tt_instance.server_info_tuple))
    else:
        logger.error("Could not trigger instance restart for server %s after connection lost: server_info_tuple not found.", host)

@pytalk_bot.event
async def on_my_kicked_from_channel(channel: TeamTalkChannel):
    server_host = "Unknown Server"
    channel_name = channel.name if channel and hasattr(channel, 'name') else 'Unknown Channel'
    tt_instance = getattr(channel.server, 'teamtalk_instance', None)
    if tt_instance and hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
        server_host = tt_instance.server_info_tuple[0]
    logger.warning("EVENT: on_my_kicked_from_channel - Kicked from '%s' on %s. Triggering forceful instance restart.", channel_name, server_host)
    if tt_instance and hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
        asyncio.create_task(force_restart_instance_on_event(*tt_instance.server_info_tuple))
    else:
        logger.error("Could not trigger instance restart for server %s after kick: server_info_tuple not found.", server_host)

@pytalk_bot.event
async def on_user_account_new(account: UserAccount):
    """Handles new user account creation, detecting if it's an update to a recently deleted account.
    """
    raw_account_username = getattr(account, 'username', 'UnknownUser')
    account_username_str = raw_account_username.decode('utf-8') if isinstance(raw_account_username, bytes) else str(raw_account_username)

    logger.info("User account '%s' created (on_user_account_new event).", account_username_str)
    print(f"User account '{account_username_str}' created.")

    aiogram_bot = pytalk_bot.aiogram_bot_ref
    if not aiogram_bot or not settings.admin_ids:
        logger.error("on_user_account_new: Aiogram bot or ADMIN_IDS not configured. Cannot send notifications.")
        return

    _ = get_translator(get_admin_lang_code())

    log_prefix = "new account"
    message_to_send = _("TeamTalk: User account '{account_username_str}' has been CREATED.").format(account_username_str=account_username_str)

    # Check if this "new" user is actually a recently deleted one (i.e., an update)
    if account_username_str in recently_deleted_users:
        deletion_time, removal_task = recently_deleted_users.pop(account_username_str)
        if time.time() - deletion_time <= DELETION_WINDOW_SECONDS:
            logger.info("Detected user '%s' recreation within %ss. Treating as a CHANGE.", account_username_str, DELETION_WINDOW_SECONDS)
            removal_task.cancel()
            message_to_send = _("TeamTalk: User account '{account_username_str}' has been CHANGED.").format(account_username_str=account_username_str)
            log_prefix = "changed"
        else:
            logger.info("User '%s' was deleted but re-created outside the time window. Treating as NEW.", account_username_str)
            # The removal task for the old deletion will proceed as normal.

    for admin_id in settings.admin_ids:
        try:
            chat_id_int = int(admin_id)
            logger.info("Attempting to send TeamTalk %s notification for '%s' to Telegram admin ID: %s", log_prefix, account_username_str, chat_id_int)
            await aiogram_bot.send_message(chat_id=chat_id_int, text=message_to_send)
        except ValueError:
            logger.error("Invalid Telegram admin ID format in config: '%s'. Must be an integer.", admin_id)
        except Exception as e:
            logger.error("Failed to send TeamTalk %s notification to Telegram admin ID %s for user '%s'. Error: %s", log_prefix, admin_id, account_username_str, e)

@pytalk_bot.event
async def on_user_account_remove(account: UserAccount):
    """Handles user account removal, scheduling a delayed notification to detect updates.
    """
    raw_account_username = getattr(account, 'username', 'UnknownUser')
    account_username_str = raw_account_username.decode('utf-8') if isinstance(raw_account_username, bytes) else str(raw_account_username)

    logger.info("User account '%s' removed. Scheduling delayed notification.", account_username_str)
    print(f"User account '{account_username_str}' removed.")

    server_host_info = "Unknown Server"
    if pytalk_bot.teamtalks:
        first_instance = pytalk_bot.teamtalks[0]
        if hasattr(first_instance, 'server_info_tuple') and first_instance.server_info_tuple:
            server_host_info = first_instance.server_info_tuple[0]
        elif first_instance.server and hasattr(first_instance.server, 'info') and first_instance.server.info:
             server_host_info = first_instance.server.info.host
    logger.info("Using server host info: %s for banning context.", server_host_info)

    asyncio.create_task(_handle_banning_on_tt_account_removal(account_username_str, server_host_info))

    if account_username_str in recently_deleted_users:
        __, old_task = recently_deleted_users[account_username_str]
        old_task.cancel()
        logger.warning("Found and cancelled a pre-existing removal task for '%s'.", account_username_str)

    removal_task = asyncio.create_task(_send_delayed_removal_notification(account_username_str))
    recently_deleted_users[account_username_str] = (time.time(), removal_task)
