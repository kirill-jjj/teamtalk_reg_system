"""Manages the TeamTalk bot's connection and reconnection logic."""
import asyncio
from collections.abc import Coroutine
import logging

import pytalk
from pytalk.enums import Status
from pytalk.enums import TeamTalkServerInfo as PyTalkTeamTalkServerInfo

from bot.core.config import settings

from ..utils.schemas import TeamTalkServerInfo
from .backoff import Backoff

logger = logging.getLogger(__name__)

active_instance_restarts: dict[str, asyncio.Task[Coroutine[None, None, None]]] = {}


async def initialize_teamtalk_connection(
    pytalk_bot_instance: pytalk.TeamTalkBot,
    host_name: str,
    tcp_port: int,
    udp_port: int,
    user_name: str,
    password: str,
    nickname: str,
    *,
    encrypted: bool,
    join_channel_path: str | None,
    join_channel_pass: str,
    bot_gender: str,
    bot_status_text: str,
) -> bool:
    """Initializes the TeamTalk connection for the bot."""
    join_channel_id = -1
    if join_channel_path and join_channel_path.strip():
        channel_to_join_str = join_channel_path.strip()
        try:
            join_channel_id = int(channel_to_join_str)
        except ValueError:
            # This part of the logic is problematic as we can't resolve the path to an ID before connecting.
            # For now, we will log a warning and not join the channel.
            # A more advanced implementation would require connecting, resolving the path, and then re-connecting or joining.
            logger.warning(
                "Joining channel by path is not supported in this version of the library. "
                "Please use a channel ID for 'tt_join_channel'."
            )

    server_info_dict = {
        "host": host_name,
        "tcp_port": tcp_port,
        "udp_port": udp_port,
        "username": user_name,
        "password": password,
        "nickname": nickname,
        "encrypted": encrypted,
        "join_channel_id": join_channel_id,
        "join_channel_password": join_channel_pass or "",
    }
    server_info_pytalk = PyTalkTeamTalkServerInfo(server_info_dict)
    try:
        server_info_model = TeamTalkServerInfo(
            host_name=host_name,
            tcp_port=tcp_port,
            udp_port=udp_port,
            user_name=user_name,
            password=password,
            nickname=nickname,
            encrypted=encrypted,
            join_channel_path=join_channel_path,
            join_channel_pass=join_channel_pass,
            bot_gender=bot_gender,
            bot_status_text=bot_status_text,
        )

        await pytalk_bot_instance.add_server(server_info_pytalk)

        if not (
            pytalk_bot_instance.teamtalks
            and pytalk_bot_instance.teamtalks[-1].logged_in
        ):
            logger.error(
                "Failed to connect or login to TeamTalk server: %s",
                host_name,
            )
            if (
                pytalk_bot_instance.teamtalks
                and pytalk_bot_instance.teamtalks[-1].server_info.hostname == host_name
                and pytalk_bot_instance.teamtalks[-1].server_info.tcp_port == tcp_port
            ):
                pytalk_bot_instance.teamtalks.pop()
                logger.info(
                    "Removed potentially failed server instance for %s:%s from list.",
                    host_name,
                    tcp_port,
                )
            return False

    except Exception:
        logger.exception("Error initializing TeamTalk connection for %s:", host_name)
        if pytalk_bot_instance.teamtalks:
            last_instance = pytalk_bot_instance.teamtalks[-1]
            if (
                hasattr(last_instance, "server_info")
                and last_instance.server_info.hostname == host_name
                and last_instance.server_info.tcp_port == tcp_port
            ):
                pytalk_bot_instance.teamtalks.pop()
                logger.info(
                    "Removed server instance for %s:%s from list due to exception.",
                    host_name,
                    tcp_port,
                )
        return False
    else:
        logger.info(
            "Successfully connected and logged into TeamTalk server: %s",
            host_name,
        )
        active_server_instance = pytalk_bot_instance.teamtalks[-1]
        active_server_instance.server_info_model = server_info_model

        if active_server_instance.server:
            active_server_instance.server.teamtalk_instance = active_server_instance

        gender_map = {
            "male": Status.online().male,
            "female": Status.online().female,
            "neutral": Status.online().neutral,
        }
        mapped_gender_status = gender_map.get(
            bot_gender.lower(), Status.online().neutral
        )
        active_server_instance.change_status(
            status_flags=mapped_gender_status, status_message=bot_status_text
        )
        logger.info(
            "Set TeamTalk status to '%s' with gender '%s'.",
            bot_status_text,
            bot_gender,
        )
        return True


async def close_teamtalk_connection(pytalk_bot_instance: pytalk.TeamTalkBot) -> None:
    """Closes all active TeamTalk connections for the bot."""
    logger.info("Attempting to shut down PyTalk bot connections...")
    if not pytalk_bot_instance.teamtalks:
        logger.info("No active TeamTalk instances to close.")
        return
    for i in range(len(pytalk_bot_instance.teamtalks) - 1, -1, -1):
        tt_instance = pytalk_bot_instance.teamtalks[i]
        host_display = "Unknown Host"
        if hasattr(tt_instance, "server_info_model") and tt_instance.server_info_model:
            host_display = tt_instance.server_info_model.host_name
        elif (
            hasattr(tt_instance, "server_info")
            and tt_instance.server_info
            and hasattr(tt_instance.server_info, "hostname")
        ):
            host_display = tt_instance.server_info.hostname

        logger.debug("Processing instance for host: %s for shutdown.", host_display)
        try:
            if hasattr(tt_instance, "logged_in") and tt_instance.logged_in:
                tt_instance.logout()
            if hasattr(tt_instance, "connected") and tt_instance.connected:
                tt_instance.disconnect()
            if hasattr(tt_instance, "super") and hasattr(
                tt_instance.super, "closeTeamTalk"
            ):
                logger.info("Closing TeamTalk SDK for instance %s...", host_display)
                tt_instance.super.closeTeamTalk()
            pytalk_bot_instance.teamtalks.pop(i)
            logger.info(
                "Disconnected, closed SDK, and removed instance for host: %s.",
                host_display,
            )
        except Exception:
            logger.exception("Error during shutdown for %s", host_display)

    if hasattr(pytalk_bot_instance, "_close_all_sdk") and not (
        pytalk_bot_instance.teamtalks
    ):
        pytalk_bot_instance._close_all_sdk()
        logger.info(
            "Called pytalk_bot_instance._close_all_sdk() as all instances "
            "were removed."
        )
    elif pytalk_bot_instance.teamtalks:
        logger.warning(
            "Not all instances removed from pytalk_bot_instance.teamtalks list "
            "during close: %s remaining.",
            len(pytalk_bot_instance.teamtalks),
        )

    logger.info("PyTalk bot shutdown process completed.")


async def launch_teamtalk_service(
    pytalk_bot_instance: pytalk.TeamTalkBot,
    host_name: str,
    tcp_port: int,
    udp_port: int,
    user_name: str,
    password: str,
    nickname: str,
    *,
    encrypted: bool,
    join_channel_path: str | None,
    join_channel_pass: str,
    bot_gender: str,
    bot_status_text: str,
) -> None:
    """Launches the TeamTalk bot service.

    This connects to the server and starts event processing.
    """
    logger.info("Starting PyTalk bot service...")
    try:
        async with pytalk_bot_instance:
            if not await initialize_teamtalk_connection(
                pytalk_bot_instance,
                host_name,
                tcp_port,
                udp_port,
                user_name,
                password,
                nickname,
                encrypted=encrypted,
                join_channel_path=join_channel_path,
                join_channel_pass=join_channel_pass,
                bot_gender=bot_gender,
                bot_status_text=bot_status_text,
            ):
                logger.error(
                    "Failed to initialize main TeamTalk connection. "
                    "Service may not work as expected."
                )
            await pytalk_bot_instance._start()
    except Exception:
        logger.exception("Exception in PyTalk bot service loop:")
    finally:
        logger.info("PyTalk bot service stopped.")


async def _shutdown_and_remove_instance(
    pytalk_bot_instance: pytalk.TeamTalkBot,
    server_key: str,
    host_name: str,
    tcp_port: int,
) -> None:
    """Finds, shuts down, and removes a specific TeamTalk instance."""
    instance_to_remove_idx = -1
    for i, tt_instance in enumerate(list(pytalk_bot_instance.teamtalks)):
        instance_matches = False
        if (hasattr(tt_instance, "server_info_model") and (
            tt_instance.server_info_model.host_name == host_name
            and tt_instance.server_info_model.tcp_port == tcp_port
        )) or (hasattr(tt_instance, "server_info") and (
            tt_instance.server_info.hostname == host_name
            and tt_instance.server_info.tcp_port == tcp_port
        )):
            instance_matches = True

        if instance_matches:
            instance_to_remove_idx = i
            logger.info(
                "Found existing instance for %s at index %s to shutdown.", server_key, i
            )
            try:
                if hasattr(tt_instance, "logged_in") and tt_instance.logged_in:
                    logger.info("Logging out instance for %s...", server_key)
                    tt_instance.logout()
                if hasattr(tt_instance, "connected") and tt_instance.connected:
                    logger.info("Disconnecting instance for %s...", server_key)
                    tt_instance.disconnect()
                if hasattr(tt_instance, "super") and hasattr(
                    tt_instance.super, "closeTeamTalk"
                ):
                    logger.info("Closing TeamTalk SDK for instance %s...", server_key)
                    tt_instance.super.closeTeamTalk()
                logger.info("Instance for %s shutdown procedures called.", server_key)
            except Exception:
                logger.exception("Error during shutdown of instance for %s", server_key)
            break

    if instance_to_remove_idx != -1:
        try:
            pytalk_bot_instance.teamtalks.pop(instance_to_remove_idx)
            logger.info(
                "Old instance for %s removed from pytalk_bot_instance.teamtalks list.",
                server_key,
            )
        except IndexError:
            logger.warning(
                "Could not pop instance at index %s for %s, list changed?",
                instance_to_remove_idx,
                server_key,
            )
    else:
        logger.info(
            "No existing instance found for %s in pytalk_bot_instance.teamtalks "
            "list, or already removed.",
            server_key,
        )


async def force_restart_instance_on_event(
    pytalk_bot_instance: pytalk.TeamTalkBot,
    server_info: TeamTalkServerInfo,
) -> None:
    """Forcefully restarts a TeamTalk connection instance.

    Typically triggered by a disconnection event.
    """
    server_key = f"{server_info.host_name}:{server_info.tcp_port}"
    if (
        server_key in active_instance_restarts
        and not active_instance_restarts[server_key].done()
    ):
        logger.warning(
            "Instance restart for %s is already in progress. Skipping.", server_key
        )
        return

    logger.info(
        "Starting forceful instance restart process for server %s...", server_key
    )

    async def restart_task() -> None:
        await _shutdown_and_remove_instance(
            pytalk_bot_instance, server_key, server_info.host_name, server_info.tcp_port
        )

        base_delay = getattr(settings, "TT_RECONNECT_BASE_DELAY", 5)
        exponent = getattr(settings, "TT_RECONNECT_EXPONENT", 2)
        max_delay = getattr(settings, "TT_RECONNECT_MAX_DELAY", 60)
        max_tries_restart = getattr(settings, "TT_RESTART_MAX_TRIES", 3)

        backoff_controller = Backoff(
            base=base_delay,
            exponent=exponent,
            max_value=max_delay,
            max_tries=max_tries_restart,
        )

        while True:
            delay = backoff_controller.delay()
            if delay is None:
                logger.error(
                    "Max restart attempts reached for server %s. Giving up.", server_key
                )
                break

            logger.info(
                "Attempting to re-initialize instance for %s (attempt %s/%s). "
                "Waiting for %.2f seconds...",
                server_key,
                backoff_controller.attempts,
                max_tries_restart,
                delay,
            )
            await asyncio.sleep(delay)

            success = await initialize_teamtalk_connection(
                pytalk_bot_instance,
                host_name=server_info.host_name,
                tcp_port=server_info.tcp_port,
                udp_port=server_info.udp_port,
                user_name=server_info.user_name,
                password=server_info.password,
                nickname=server_info.nickname,
                encrypted=server_info.encrypted,
                join_channel_path=server_info.join_channel_path,
                join_channel_pass=server_info.join_channel_pass,
                bot_gender=server_info.bot_gender,
                bot_status_text=server_info.bot_status_text,
            )

            if success:
                logger.info(
                    "Successfully re-initialized and connected instance for server %s.",
                    server_key,
                )
                break
            logger.warning(
                "Failed to re-initialize instance for %s on attempt %s.",
                server_key,
                backoff_controller.attempts,
            )

        active_instance_restarts.pop(server_key, None)

    task = asyncio.create_task(restart_task())
    active_instance_restarts[server_key] = task
