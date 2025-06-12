import logging
from typing import Optional
import asyncio
import pytalk
from pytalk.enums import TeamTalkServerInfo, Status

from bot.core import config
from .backoff import Backoff

logger = logging.getLogger(__name__)

pytalk_bot = pytalk.TeamTalkBot(client_name=config.CLIENT_NAME)
active_instance_restarts = {} # Key: server_host_port, Value: asyncio.Task

async def initialize_teamtalk_connection(
    host_name: str, tcp_port: int, udp_port: int, user_name: str, password: str,
    nickname: str, encrypted: bool, join_channel_path: Optional[str],
    join_channel_pass: str, bot_gender: str, bot_status_text: str
) -> bool:
    server_info_pytalk = TeamTalkServerInfo(
        host=host_name, tcp_port=tcp_port, udp_port=udp_port,
        username=user_name, password=password, nickname=nickname,
        encrypted=encrypted, join_channel_id=-1, join_channel_password=""
    )
    try:
        # Store parameters before add_server in case add_server fails but still adds to teamtalks list partially
        current_server_info_tuple = (
            host_name, tcp_port, udp_port, user_name, password, nickname, encrypted,
            join_channel_path, join_channel_pass, bot_gender, bot_status_text
        )

        await pytalk_bot.add_server(server_info_pytalk)

        if pytalk_bot.teamtalks and pytalk_bot.teamtalks[-1].logged_in:
            logger.info(f"Successfully connected and logged into TeamTalk server: {host_name}")
            active_server_instance = pytalk_bot.teamtalks[-1]

            # Store original parameters on the instance for potential reconnection/restart
            active_server_instance.server_info_tuple = current_server_info_tuple

            # Associate the TeamTalkInstance with the server object for easy access in events
            if active_server_instance.server:
                 active_server_instance.server.teamtalk_instance = active_server_instance

            if join_channel_path and join_channel_path.strip():
                channel_to_join_str = join_channel_path.strip()
                join_password = join_channel_pass if join_channel_pass else ""
                try:
                    channel_id_int = int(channel_to_join_str)
                    logger.info(f"Attempting to join channel by ID: {channel_id_int}")
                    active_server_instance.join_channel_by_id(id=channel_id_int, password=join_password)
                except ValueError:
                    logger.info(f"Attempting to join channel by path: '{channel_to_join_str}'")
                    try:
                        channel_obj = active_server_instance.get_channel_from_path(channel_to_join_str)
                        if channel_obj and channel_obj.id is not None:
                            active_server_instance.join_channel_by_id(id=channel_obj.id, password=join_password)
                        else:
                            logger.warning(f"Channel path '{channel_to_join_str}' not found.")
                    except Exception as e_path:
                        logger.error(f"Error joining by path '{channel_to_join_str}': {e_path}")
                except Exception as e_join:
                     logger.error(f"Error joining channel '{channel_to_join_str}': {e_join}")

            gender_map = {"male": Status.online.male, "female": Status.online.female, "neutral": Status.online.neutral}
            mapped_gender_status = gender_map.get(bot_gender.lower(), Status.online.neutral)
            active_server_instance.change_status(status_flags=mapped_gender_status, status_message=bot_status_text)
            logger.info(f"Set TeamTalk status to '{bot_status_text}' with gender '{bot_gender}'.")
            return True
        else:
            logger.error(f"Failed to connect or login to TeamTalk server: {host_name}")
            # Attempt to remove the potentially partially added server instance
            if pytalk_bot.teamtalks and pytalk_bot.teamtalks[-1].server_info.host == host_name and pytalk_bot.teamtalks[-1].server_info.tcp_port == tcp_port:
                pytalk_bot.teamtalks.pop()
                logger.info(f"Removed potentially failed server instance for {host_name}:{tcp_port} from list.")
            return False
    except Exception as e:
        logger.error(f"Error initializing TeamTalk connection for {host_name}: {e}", exc_info=True)
        # Attempt to remove the potentially partially added server instance on general exception too
        if pytalk_bot.teamtalks:
            # This removal logic might be too aggressive or could target wrong instance if multiple servers in list
            # A more robust way would be to find the specific instance if possible
            last_instance = pytalk_bot.teamtalks[-1]
            if hasattr(last_instance, 'server_info') and last_instance.server_info.host == host_name and last_instance.server_info.tcp_port == tcp_port:
                 pytalk_bot.teamtalks.pop()
                 logger.info(f"Removed server instance for {host_name}:{tcp_port} from list due to exception during init.")
        return False

async def close_teamtalk_connection():
    logger.info("Attempting to shut down PyTalk bot connections...")
    if not pytalk_bot.teamtalks:
        logger.info("No active TeamTalk instances to close.")
        return
    for i in range(len(pytalk_bot.teamtalks) -1, -1, -1): # Iterate backwards for safe removal
        tt_instance = pytalk_bot.teamtalks[i]
        host_display = "Unknown Host"
        # Check server_info_tuple first as it's set by our code
        if hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
            host_display = tt_instance.server_info_tuple[0]
        elif hasattr(tt_instance, 'server_info') and tt_instance.server_info and hasattr(tt_instance.server_info, 'host'):
             host_display = tt_instance.server_info.host

        logger.debug(f"Processing instance for host: {host_display} for shutdown.")
        try:
            if hasattr(tt_instance, 'logged_in') and tt_instance.logged_in: tt_instance.logout()
            if hasattr(tt_instance, 'connected') and tt_instance.connected: tt_instance.disconnect()
            if hasattr(tt_instance, 'super') and hasattr(tt_instance.super, 'closeTeamTalk'):
                logger.info(f"Closing TeamTalk SDK for instance {host_display}...")
                tt_instance.super.closeTeamTalk()
            pytalk_bot.teamtalks.pop(i)
            logger.info(f"Disconnected, closed SDK, and removed instance for host: {host_display}.")
        except Exception as e: logger.error(f"Error during shutdown for {host_display}: {e}", exc_info=True)

    # This might be redundant if all instances are closed and popped correctly
    if hasattr(pytalk_bot, '_close_all_sdk') and not pytalk_bot.teamtalks:
        pytalk_bot._close_all_sdk()
        logger.info("Called pytalk_bot._close_all_sdk() as all instances were removed.")
    elif pytalk_bot.teamtalks:
        logger.warning(f"Not all instances removed from pytalk_bot.teamtalks list during close: {len(pytalk_bot.teamtalks)} remaining.")

    logger.info("PyTalk bot shutdown process completed.")

async def launch_teamtalk_service(
    host_name: str, tcp_port: int, udp_port: int, user_name: str, password: str,
    nickname: str, encrypted: bool, join_channel_path: Optional[str],
    join_channel_pass: str, bot_gender: str, bot_status_text: str
):
    logger.info("Starting PyTalk bot service...")
    try:
        async with pytalk_bot:
            if not await initialize_teamtalk_connection(
                host_name, tcp_port, udp_port, user_name, password, nickname,
                encrypted, join_channel_path, join_channel_pass, bot_gender, bot_status_text
            ):
                logger.error("Failed to initialize main TeamTalk connection. Service may not work as expected.")
            await pytalk_bot._start()
    except Exception as e:
        logger.exception("Exception in PyTalk bot service loop:", exc_info=True)
    finally:
        logger.info("PyTalk bot service stopped.")

async def force_restart_instance_on_event(
    host_name: str,
    tcp_port: int,
    udp_port: int,
    user_name: str,
    password: str,
    nickname: str,
    encrypted: bool,
    join_channel_path: Optional[str],
    join_channel_pass: str,
    bot_gender: str,
    bot_status_text: str
):
    server_key = f"{host_name}:{tcp_port}"
    if server_key in active_instance_restarts and not active_instance_restarts[server_key].done():
        logger.warning(f"Instance restart for {server_key} is already in progress. Skipping.")
        return

    logger.info(f"Starting forceful instance restart process for server {server_key}...")

    original_args = (host_name, tcp_port, udp_port, user_name, password, nickname, encrypted,
                     join_channel_path, join_channel_pass, bot_gender, bot_status_text)

    async def restart_task():
        instance_to_remove_idx = -1
        for i, tt_instance in enumerate(list(pytalk_bot.teamtalks)):
            instance_matches = False
            if hasattr(tt_instance, 'server_info_tuple'): # Primary check
                if tt_instance.server_info_tuple[0] == host_name and tt_instance.server_info_tuple[1] == tcp_port:
                    instance_matches = True
            elif hasattr(tt_instance, 'server_info'): # Fallback
                 if tt_instance.server_info.host == host_name and tt_instance.server_info.tcp_port == tcp_port:
                    instance_matches = True

            if instance_matches:
                instance_to_remove_idx = i
                logger.info(f"Found existing instance for {server_key} at index {i} to shutdown.")
                try:
                    if hasattr(tt_instance, 'logged_in') and tt_instance.logged_in:
                        logger.info(f"Logging out instance for {server_key}...")
                        tt_instance.logout()
                    if hasattr(tt_instance, 'connected') and tt_instance.connected:
                        logger.info(f"Disconnecting instance for {server_key}...")
                        tt_instance.disconnect()
                    if hasattr(tt_instance, 'super') and hasattr(tt_instance.super, 'closeTeamTalk'):
                        logger.info(f"Closing TeamTalk SDK for instance {server_key}...")
                        tt_instance.super.closeTeamTalk()
                    logger.info(f"Instance for {server_key} shutdown procedures called.")
                except Exception as e_shutdown:
                    logger.error(f"Error during shutdown of instance for {server_key}: {e_shutdown}", exc_info=True)
                break

        if instance_to_remove_idx != -1:
            try:
                pytalk_bot.teamtalks.pop(instance_to_remove_idx)
                logger.info(f"Old instance for {server_key} removed from pytalk_bot.teamtalks list.")
            except IndexError:
                logger.warning(f"Could not pop instance at index {instance_to_remove_idx} for {server_key}, list changed?")
        else:
            logger.info(f"No existing instance found for {server_key} in pytalk_bot.teamtalks list, or already removed.")

        base_delay = getattr(config, 'TT_RECONNECT_BASE_DELAY', 5)
        exponent = getattr(config, 'TT_RECONNECT_EXPONENT', 2)
        max_delay = getattr(config, 'TT_RECONNECT_MAX_DELAY', 60)
        # Use a specific max_tries for restarts, could be different from general reconnection
        max_tries_restart = getattr(config, 'TT_RESTART_MAX_TRIES', 3)

        backoff_controller = Backoff(base=base_delay, exponent=exponent, max_value=max_delay, max_tries=max_tries_restart)

        while True:
            delay = backoff_controller.delay()
            if delay is None:
                logger.error(f"Max restart attempts reached for server {server_key}. Giving up.")
                break

            logger.info(f"Attempting to re-initialize instance for {server_key} (attempt {backoff_controller.attempts}/{max_tries_restart}). Waiting for {delay:.2f} seconds...")
            await asyncio.sleep(delay)

            success = await initialize_teamtalk_connection(*original_args)

            if success:
                logger.info(f"Successfully re-initialized and connected instance for server {server_key}.")
                break
            else:
                logger.warning(f"Failed to re-initialize instance for {server_key} on attempt {backoff_controller.attempts}.")

        if server_key in active_instance_restarts:
            del active_instance_restarts[server_key]

    task = asyncio.create_task(restart_task())
    active_instance_restarts[server_key] = task
