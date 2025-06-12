import logging
import asyncio

from .connection import pytalk_bot, force_restart_instance_on_event
from pytalk.server import Server as TeamTalkServer
from pytalk.message import Message
from pytalk import Channel as TeamTalkChannel

logger = logging.getLogger(__name__)

# Removed kick_event_timestamps and KICK_CONNECTION_LOST_THRESHOLD_SECONDS

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
