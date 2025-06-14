import asyncio
import logging
from typing import List

from pytalk import Channel as TeamTalkChannel
from pytalk import UserAccount, user, UserType, TeamTalkInstance
from pytalk.message import Message
from pytalk.server import Server as TeamTalkServer

from bot.core import config
from bot.core.db.crud import add_banned_user, get_telegram_id_by_teamtalk_username # Added imports
from bot.core.db.session import AsyncSessionLocal # Added import
from .connection import force_restart_instance_on_event, pytalk_bot

logger = logging.getLogger(__name__)


# Helper function for banning
async def _handle_banning_on_tt_account_removal(tt_username: str, server_host_info: str):
    logger.info(f"Attempting to process ban for TeamTalk user '{tt_username}' deleted from server '{server_host_info}'.")
    async with AsyncSessionLocal() as session:
        try:
            telegram_id = await get_telegram_id_by_teamtalk_username(session, tt_username)
            if telegram_id:
                logger.info(f"Found Telegram ID {telegram_id} for TeamTalk user '{tt_username}'. Proceeding to ban.")
                await add_banned_user(
                    db_session=session,
                    telegram_id=telegram_id,
                    teamtalk_username=tt_username,
                    reason=f"Account deleted from TeamTalk server: {server_host_info}"
                    # banned_by_admin_id will be None by default (auto-ban)
                )
                logger.info(f"Successfully processed ban for Telegram ID {telegram_id} (TeamTalk: {tt_username}).")
            else:
                logger.warning(f"No Telegram ID found for TeamTalk user '{tt_username}'. Cannot add to bot's ban list.")
        except Exception as e:
            logger.error(f"Error during automatic banning process for TeamTalk user '{tt_username}': {e}", exc_info=True)


def get_admin_users(teamtalk_instance: TeamTalkInstance) -> List[user]:
    """
    Retrieves a list of admin users from the server.

    Args:
        teamtalk_instance: The TeamTalkInstance to get users from.

    Returns:
        A list of pytalk.User objects who are admins.
    """
    admin_users: List[user] = []
    if not teamtalk_instance or not hasattr(teamtalk_instance, 'server'):
        logger.warning("get_admin_users: Invalid teamtalk_instance or server attribute missing.")
        return admin_users

    try:
        all_users: List[user] = teamtalk_instance.server.get_users()
    except Exception as e:
        logger.error(f"get_admin_users: Error getting users from server: {e}")
        return admin_users

    for user in all_users:
        try:
            if hasattr(user, 'user_type') and user.user_type == UserType.ADMIN:
                admin_users.append(user)
        except Exception as e:
            logger.error(f"get_admin_users: Error processing user {getattr(user, 'id', 'UnknownID')}: {e}")
            # Continue processing other users
    return admin_users

@pytalk_bot.event
async def on_ready():
    logger.info("PyTalk Bot is ready (on_ready event).")

@pytalk_bot.event
async def on_my_login(server: TeamTalkServer):
    host_info = server.info.host if server and hasattr(server, 'info') and server.info else 'Unknown Server'
    logger.info(f"Successfully logged in to server: {host_info} (on_my_login event).")

    tt_instance = getattr(server, 'teamtalk_instance', None)
    if not tt_instance:
        for inst in pytalk_bot.teamtalks:
            if inst.server is server:
                tt_instance = inst
                break

    if tt_instance:
        logger.info(f"Bot's user ID on {host_info}: {tt_instance.getMyUserID()}")
        current_channel_id = tt_instance.getMyChannelID()
        if current_channel_id > 0:
            try:
                channel_obj = tt_instance.get_channel(current_channel_id)
                channel_name = channel_obj.name if channel_obj and hasattr(channel_obj, 'name') else 'Unknown Channel'
                logger.info(f"Bot is currently in channel: {channel_name} (ID: {current_channel_id}) on {host_info}")
            except Exception as e:
                logger.warning(f"Could not get channel info for ID {current_channel_id} on {host_info}: {e}")
        else:
            logger.info(f"Bot is not in any specific channel on {host_info} (currently in root or no channel).")
    else:
        logger.warning(f"Could not find matching TeamTalkInstance for server {host_info} in on_my_login.")

@pytalk_bot.event
async def on_message(message: Message):
    logger.info(f"Received message (on_message event): Type: {type(message).__name__}, From ID: {message.from_id}, Content: '{message.content[:50]}...'")

@pytalk_bot.event
async def on_error(event_name: str, *args, **kwargs):
    logger.error(f"Error in event handler '{event_name}'. Args: {args}, Kwargs: {kwargs}", exc_info=True)

@pytalk_bot.event
async def on_my_connect(server: TeamTalkServer):
   host_info = server.info.host if server and hasattr(server, 'info') and server.info else 'Unknown Server'
   logger.info(f"Successfully connected to server: {host_info} (on_my_connect event)")

@pytalk_bot.event
async def on_my_disconnect(server: TeamTalkServer):
    host = server.info.host if server and hasattr(server, 'info') and server.info else 'Unknown Server'
    logger.info(f"Bot gracefully disconnected from server: {host} (on_my_disconnect event). No reconnection attempt will be made by this specific handler.")

@pytalk_bot.event
async def on_my_connection_lost(server: TeamTalkServer):
    host = "Unknown Server"
    tt_instance = getattr(server, 'teamtalk_instance', None)

    if tt_instance and hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
        host = tt_instance.server_info_tuple[0]
    elif server and hasattr(server, 'info') and server.info:
        host = server.info.host
        if not tt_instance: # Try to find instance again if only server.info was available initially
             for inst in pytalk_bot.teamtalks:
                if hasattr(inst, 'server_info_tuple'):
                    inst_host, inst_tcp, *_ = inst.server_info_tuple
                    if inst_host == host and hasattr(server.info, 'tcp_port') and inst_tcp == server.info.tcp_port:
                        tt_instance = inst
                        break
                elif inst.server is server:
                     tt_instance = inst
                     break

    logger.warning(f"EVENT: on_my_connection_lost - Connection lost from server {host}. Triggering forceful instance restart.")

    if tt_instance and hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
        asyncio.create_task(force_restart_instance_on_event(*tt_instance.server_info_tuple))
    else:
        logger.error(f"Could not trigger instance restart for server {host} after connection lost: server_info_tuple not found on instance or instance unavailable.")

@pytalk_bot.event
async def on_my_kicked_from_channel(channel: TeamTalkChannel):
    server_host = "Unknown Server"
    channel_name = channel.name if channel and hasattr(channel, 'name') else 'Unknown Channel'
    tt_instance = None

    if channel and hasattr(channel, 'server') and channel.server:
        tt_instance = getattr(channel.server, 'teamtalk_instance', None)
        if tt_instance and hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
            server_host = tt_instance.server_info_tuple[0]
        elif hasattr(channel.server, 'info') and channel.server.info:
            server_host = channel.server.info.host
            if not tt_instance: # Try to find instance again if only server.info was available
                for inst in pytalk_bot.teamtalks:
                    if hasattr(inst, 'server_info_tuple'):
                        inst_host, inst_tcp, *_ = inst.server_info_tuple
                        if inst_host == server_host and hasattr(channel.server.info, 'tcp_port') and inst_tcp == channel.server.info.tcp_port:
                            tt_instance = inst
                            break
                    elif inst.server is channel.server:
                        tt_instance = inst
                        break

    logger.warning(f"EVENT: on_my_kicked_from_channel - Kicked from channel '{channel_name}' on server {server_host}. Triggering forceful instance restart.")

    if tt_instance and hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
        asyncio.create_task(force_restart_instance_on_event(*tt_instance.server_info_tuple))
    else:
        logger.error(f"Could not trigger instance restart for server {server_host} after kick: server_info_tuple not found on instance or instance unavailable.")


@pytalk_bot.event
async def on_user_account_new(account: UserAccount):
    """
    Handles the event when a new user account is created on the server.
    Notifies admin users via Telegram about the account creation.
    """
    raw_account_username = getattr(account, 'username', 'UnknownUser')
    account_username_str = raw_account_username.decode('utf-8') if isinstance(raw_account_username, bytes) else str(raw_account_username)

    logger.info(f"User account '{account_username_str}' created (on_user_account_new event).")
    print(f"User account '{account_username_str}' created.") # Keep console print for immediate feedback

    aiogram_bot = pytalk_bot.aiogram_bot_ref
    if not aiogram_bot:
        logger.error("on_user_account_new: Aiogram bot reference not found on pytalk_bot. Cannot send Telegram notifications.")
        return

    if not config.ADMIN_IDS:
        logger.warning("on_user_account_new: No ADMIN_IDS configured in bot.core.config. Cannot send Telegram notifications.")
        return

    message_to_send = (
        f"TeamTalk: User account '{account_username_str}' has been CREATED. "
        f"(Note: The admin who performed this action cannot be identified by the bot at this time.)"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            # Ensure admin_id is an integer, as expected by aiogram
            chat_id_int = int(admin_id)
            logger.info(f"Attempting to send TeamTalk new account notification for '{account_username_str}' to Telegram admin ID: {chat_id_int}")
            await aiogram_bot.send_message(chat_id=chat_id_int, text=message_to_send)
        except ValueError:
            logger.error(f"Invalid Telegram admin ID format in config: '{admin_id}'. Must be an integer.")
        except Exception as e:
            logger.error(f"Failed to send TeamTalk new account notification to Telegram admin ID {admin_id} for user '{account_username_str}'. Error: {e}")

@pytalk_bot.event
async def on_user_account_remove(account: UserAccount):
    """
    Handles the event when a user account is removed from the server.
    Notifies admin users via Telegram about the account removal.
    """
    raw_account_username = getattr(account, 'username', 'UnknownUser')
    account_username_str = raw_account_username.decode('utf-8') if isinstance(raw_account_username, bytes) else str(raw_account_username)

    logger.info(f"User account '{account_username_str}' removed (on_user_account_remove event).")
    print(f"User account '{account_username_str}' removed.") # Keep console print for immediate feedback

    # Determine server_host_info
    server_host_info = "Unknown Server"
    # The 'account' object from pytalk's on_user_account_remove might not directly have server info.
    # We might need to infer it from the pytalk_bot instance or pass it if available.
    # For now, let's assume we might not have direct access to specific server instance here easily.
    # If multiple servers are connected, this becomes more complex.
    # A more robust solution might involve iterating through pytalk_bot.teamtalks
    # but that might be slow or error-prone if the account object doesn't link back to its server.
    # For a single server setup, it might be okay to fetch from config or a shared state.
    # Let's use a placeholder and log a warning.
    # A better approach would be to get the server from the instance that triggered the event,
    # if the `account` object had a reference to its `TeamTalkInstance` or `Server`.
    # Pytalk's `account` in `on_user_account_remove` doesn't directly provide server details.
    # We will try to get it from the first available instance, assuming single server context for this feature.
    if pytalk_bot.teamtalks:
        first_instance = pytalk_bot.teamtalks[0] # Get the first (presumably only) instance
        if hasattr(first_instance, 'server_info_tuple') and first_instance.server_info_tuple:
            server_host_info = first_instance.server_info_tuple[0]
        elif first_instance.server and hasattr(first_instance.server, 'info') and first_instance.server.info:
             server_host_info = first_instance.server.info.host
    logger.info(f"Using server host info: {server_host_info} for banning context.")


    # Call the helper function to handle banning
    asyncio.create_task(_handle_banning_on_tt_account_removal(account_username_str, server_host_info))

    aiogram_bot = pytalk_bot.aiogram_bot_ref
    if not aiogram_bot:
        logger.error("on_user_account_remove: Aiogram bot reference not found on pytalk_bot. Cannot send Telegram notifications.")
        return

    if not config.ADMIN_IDS:
        logger.warning("on_user_account_remove: No ADMIN_IDS configured in bot.core.config. Cannot send Telegram notifications.")
        return

    message_to_send = (
        f"TeamTalk: User account '{account_username_str}' has been REMOVED. "
        f"(Note: The admin who performed this action cannot be identified by the bot at this time.)"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            # Ensure admin_id is an integer, as expected by aiogram
            chat_id_int = int(admin_id)
            logger.info(f"Attempting to send TeamTalk account removal notification for '{account_username_str}' to Telegram admin ID: {chat_id_int}")
            await aiogram_bot.send_message(chat_id=chat_id_int, text=message_to_send)
        except ValueError:
            logger.error(f"Invalid Telegram admin ID format in config: '{admin_id}'. Must be an integer.")
        except Exception as e:
            logger.error(f"Failed to send TeamTalk account removal notification to Telegram admin ID {admin_id} for user '{account_username_str}'. Error: {e}")
