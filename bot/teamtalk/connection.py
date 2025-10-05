"""Manages the TeamTalk bot's connection and reconnection logic."""
import asyncio
import logging

import pytalk
from pytalk.enums import Status, TeamTalkServerInfo

from bot.core.config import settings

from .backoff import Backoff

logger = logging.getLogger(__name__)

active_instance_restarts = {} # Key: server_host_port, Value: asyncio.Task

async def initialize_teamtalk_connection(
    pytalk_bot_instance: pytalk.TeamTalkBot, # New argument
    host_name: str, tcp_port: int, udp_port: int, user_name: str, password: str,
    nickname: str, encrypted: bool, join_channel_path: str | None,
    join_channel_pass: str, bot_gender: str, bot_status_text: str
) -> bool:
    """Initializes the TeamTalk connection for the bot."""
    server_info_pytalk = TeamTalkServerInfo(
        host=host_name, tcp_port=tcp_port, udp_port=udp_port,
        username=user_name, password=password, nickname=nickname,
        encrypted=encrypted, join_channel_id=-1, join_channel_password=""
    )
    try:
        # Store parameters before add_server in case add_server fails but
        # still adds to teamtalks list partially
        current_server_info_tuple = (
            host_name, tcp_port, udp_port, user_name, password, nickname, encrypted,
            join_channel_path, join_channel_pass, bot_gender, bot_status_text
        )

        await pytalk_bot_instance.add_server(server_info_pytalk)

        if (
            pytalk_bot_instance.teamtalks
            and pytalk_bot_instance.teamtalks[-1].logged_in
        ):
            logger.info(
                "Successfully connected and logged into TeamTalk server: %s",
                host_name,
            )
            active_server_instance = pytalk_bot_instance.teamtalks[-1]

            # Store original parameters on the instance for potential
            # reconnection/restart
            active_server_instance.server_info_tuple = current_server_info_tuple

            # Associate the TeamTalkInstance with the server object for easy
            # access in events
            if active_server_instance.server:
                 active_server_instance.server.teamtalk_instance = (
                    active_server_instance
                )

            if join_channel_path and join_channel_path.strip():
                channel_to_join_str = join_channel_path.strip()
                join_password = join_channel_pass if join_channel_pass else ""
                try:
                    channel_id_int = int(channel_to_join_str)
                    logger.info("Attempting to join channel by ID: %s", channel_id_int)
                    active_server_instance.join_channel_by_id(
                        id=channel_id_int, password=join_password
                    )
                except ValueError:
                    logger.info(
                        "Attempting to join channel by path: '%s'", channel_to_join_str
                    )
                    try:
                        channel_obj = (
                            active_server_instance.get_channel_from_path(
                                channel_to_join_str
                            )
                        )
                        if channel_obj and channel_obj.id is not None:
                            active_server_instance.join_channel_by_id(
                                id=channel_obj.id, password=join_password
                            )
                        else:
                            logger.warning("Channel path '%s' not found.", channel_to_join_str)
                    except Exception as e_path:
                        logger.exception("Error joining by path '%s': %s", channel_to_join_str, e_path)
                except Exception as e_join:
                    logger.exception("Error joining channel '%s': %s", channel_to_join_str, e_join)

            gender_map = {
                "male": Status.online.male,
                "female": Status.online.female,
                "neutral": Status.online.neutral,
            }
            mapped_gender_status = gender_map.get(
                bot_gender.lower(), Status.online.neutral
            )
            active_server_instance.change_status(
                status_flags=mapped_gender_status, status_message=bot_status_text
            )
            logger.info(
                "Set TeamTalk status to '%s' with gender '%s'.",
                bot_status_text, bot_gender,
            )
            return True
        logger.error("Failed to connect or login to TeamTalk server: %s", host_name)
        # Attempt to remove the potentially partially added server instance
        if (
            pytalk_bot_instance.teamtalks
            and pytalk_bot_instance.teamtalks[-1].server_info.host == host_name
            and pytalk_bot_instance.teamtalks[-1].server_info.tcp_port == tcp_port
        ):
            pytalk_bot_instance.teamtalks.pop()
            logger.info(
                "Removed potentially failed server instance for %s:%s from list.",
                host_name, tcp_port,
            )
        return False
    except Exception as e:
        logger.exception(
            "Error initializing TeamTalk connection for %s: %s", host_name, e
        )
        # Attempt to remove the potentially partially added server instance
        # on general exception too
        if pytalk_bot_instance.teamtalks:
            # This removal logic might be too aggressive or could target wrong
            # instance if multiple servers in list
            # A more robust way would be to find the specific instance if possible
            last_instance = pytalk_bot_instance.teamtalks[-1]
            if (
                hasattr(last_instance, 'server_info')
                and last_instance.server_info.host == host_name
                and last_instance.server_info.tcp_port == tcp_port
            ):
                 pytalk_bot_instance.teamtalks.pop()
                 logger.info(
                    "Removed server instance for %s:%s from list due to exception during init.",
                    host_name, tcp_port,
                )
        return False

async def close_teamtalk_connection(pytalk_bot_instance: pytalk.TeamTalkBot) -> None:
    """Closes all active TeamTalk connections for the bot."""
    logger.info("Attempting to shut down PyTalk bot connections...")
    if not pytalk_bot_instance.teamtalks:
        logger.info("No active TeamTalk instances to close.")
        return
    for i in range(len(pytalk_bot_instance.teamtalks) - 1, -1, -1):  # Iterate backwards for safe removal
        tt_instance = pytalk_bot_instance.teamtalks[i]
        host_display = "Unknown Host"
        # Check server_info_tuple first as it's set by our code
        if hasattr(tt_instance, 'server_info_tuple') and tt_instance.server_info_tuple:
            host_display = tt_instance.server_info_tuple[0]
        elif (
            hasattr(tt_instance, 'server_info')
            and tt_instance.server_info
            and hasattr(tt_instance.server_info, 'host')
        ):
             host_display = tt_instance.server_info.host

        logger.debug("Processing instance for host: %s for shutdown.", host_display)
        try:
            if hasattr(tt_instance, 'logged_in') and tt_instance.logged_in:
                tt_instance.logout()
            if hasattr(tt_instance, 'connected') and tt_instance.connected:
                tt_instance.disconnect()
            if hasattr(tt_instance, 'super') and hasattr(tt_instance.super, 'closeTeamTalk'):
                logger.info("Closing TeamTalk SDK for instance %s...", host_display)
                tt_instance.super.closeTeamTalk()
            pytalk_bot_instance.teamtalks.pop(i)
            logger.info(
                "Disconnected, closed SDK, and removed instance for host: %s.",
                host_display,
            )
        except Exception as e:
            logger.error(
                f"Error during shutdown for {host_display}: {e}", exc_info=True
            )

    # This might be redundant if all instances are closed and popped correctly
    if hasattr(pytalk_bot_instance, '_close_all_sdk') and not (
        pytalk_bot_instance.teamtalks
    ):
        pytalk_bot_instance._close_all_sdk()
        logger.info(
            "Called pytalk_bot_instance._close_all_sdk() as all instances were removed."
        )
    elif pytalk_bot_instance.teamtalks:
        logger.warning(
            "Not all instances removed from pytalk_bot_instance.teamtalks list "
            "during close: %s remaining.",
            len(pytalk_bot_instance.teamtalks),
        )

    logger.info("PyTalk bot shutdown process completed.")

async def launch_teamtalk_service(
    pytalk_bot_instance: pytalk.TeamTalkBot, # New argument
    host_name: str, tcp_port: int, udp_port: int, user_name: str, password: str,
    nickname: str, encrypted: bool, join_channel_path: str | None,
    join_channel_pass: str, bot_gender: str, bot_status_text: str
) -> None:
    """Launches the TeamTalk bot service, connecting to the server and starting event processing."""
    logger.info("Starting PyTalk bot service...")
    try:
        async with pytalk_bot_instance:
            if not await initialize_teamtalk_connection(
                host_name, tcp_port, udp_port, user_name, password, nickname,
                encrypted, join_channel_path, join_channel_pass, bot_gender, bot_status_text
            ):
                logger.error("Failed to initialize main TeamTalk connection. Service may not work as expected.")
            await pytalk_bot_instance._start()
    except Exception:
        logger.exception("Exception in PyTalk bot service loop:", exc_info=True)
    finally:
        logger.info("PyTalk bot service stopped.")

async def force_restart_instance_on_event(
    pytalk_bot_instance: pytalk.TeamTalkBot, # New argument
    host_name: str,
    tcp_port: int,
    udp_port: int,
    user_name: str,
    password: str,
    nickname: str,
    encrypted: bool,
    join_channel_path: str | None,
    join_channel_pass: str,
    bot_gender: str,
    bot_status_text: str
):
    server_key = f"{host_name}:{tcp_port}"
    if server_key in active_instance_restarts and not active_instance_restarts[server_key].done():
        logger.warning("Instance restart for %s is already in progress. Skipping.", server_key)
        return

    logger.info("Starting forceful instance restart process for server %s...", server_key)

    original_args = (host_name, tcp_port, udp_port, user_name, password, nickname, encrypted,
                     join_channel_path, join_channel_pass, bot_gender, bot_status_text)

    async def restart_task():
        instance_to_remove_idx = -1
        for i, tt_instance in enumerate(list(pytalk_bot_instance.teamtalks)):
            instance_matches = False
            if hasattr(tt_instance, 'server_info_tuple'): # Primary check
                if tt_instance.server_info_tuple[0] == host_name and tt_instance.server_info_tuple[1] == tcp_port:
                    instance_matches = True
            elif hasattr(tt_instance, 'server_info'): # Fallback
                 if tt_instance.server_info.host == host_name and tt_instance.server_info.tcp_port == tcp_port:
                    instance_matches = True

            if instance_matches:
                instance_to_remove_idx = i
                logger.info("Found existing instance for %s at index %s to shutdown.", server_key, i)
                try:
                    if hasattr(tt_instance, 'logged_in') and tt_instance.logged_in:
                        logger.info("Logging out instance for %s...", server_key)
                        tt_instance.logout()
                    if hasattr(tt_instance, 'connected') and tt_instance.connected:
                        logger.info("Disconnecting instance for %s...", server_key)
                        tt_instance.disconnect()
                    if hasattr(tt_instance, 'super') and hasattr(tt_instance.super, 'closeTeamTalk'):
                        logger.info("Closing TeamTalk SDK for instance %s...", server_key)
                        tt_instance.super.closeTeamTalk()
                    logger.info("Instance for %s shutdown procedures called.", server_key)
                except Exception as e_shutdown:
                    logger.error(f"Error during shutdown of instance for {server_key}: {e_shutdown}", exc_info=True)
                break

        if instance_to_remove_idx != -1:
            try:
                pytalk_bot_instance.teamtalks.pop(instance_to_remove_idx)
                logger.info("Old instance for %s removed from pytalk_bot_instance.teamtalks list.", server_key)
            except IndexError:
                logger.warning("Could not pop instance at index %s for %s, list changed?", instance_to_remove_idx, server_key)
            else:
                logger.info("No existing instance found for %s in pytalk_bot_instance.teamtalks list, or already removed.", server_key)
        base_delay = getattr(settings, 'TT_RECONNECT_BASE_DELAY', 5)
        exponent = getattr(settings, 'TT_RECONNECT_EXPONENT', 2)
        max_delay = getattr(settings, 'TT_RECONNECT_MAX_DELAY', 60)
        # Use a specific max_tries for restarts, could be different from general reconnection
        max_tries_restart = getattr(settings, 'TT_RESTART_MAX_TRIES', 3)

        backoff_controller = Backoff(base=base_delay, exponent=exponent, max_value=max_delay, max_tries=max_tries_restart)

        while True:
            delay = backoff_controller.delay()
            if delay is None:
                logger.error("Max restart attempts reached for server %s. Giving up.", server_key)
                break

            logger.info("Attempting to re-initialize instance for %s (attempt %s/%s). Waiting for %.2f seconds...", server_key, backoff_controller.attempts, max_tries_restart, delay)
            await asyncio.sleep(delay)

            success = await initialize_teamtalk_connection(*original_args)

            if success:
                logger.info("Successfully re-initialized and connected instance for server %s.", server_key)
                break
            logger.warning("Failed to re-initialize instance for %s on attempt %s.", server_key, backoff_controller.attempts)

        active_instance_restarts.pop(server_key, None)

    task = asyncio.create_task(restart_task())
    active_instance_restarts[server_key] = task
