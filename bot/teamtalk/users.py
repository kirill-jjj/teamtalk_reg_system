"""This module contains functions for interacting with TeamTalk users."""
import logging

import pytalk
from pytalk.enums import UserType as PyTalkUserType
from pytalk.implementation.TeamTalkPy import TeamTalk5
from pytalk.instance import TeamTalkInstance
from pytalk.permission import Permission as PyTalkPermission

from bot.utils.schemas import TeamTalkRegistrationArtefacts

logger = logging.getLogger(__name__)


# --- Helper Functions ---
def _calculate_pytalk_user_rights(
    teamtalk_default_user_rights_list: list[str],
) -> int:
    """Calculates the PyTalk user rights bitmask from the provided list."""
    pytalk_user_rights = 0
    for right_string in teamtalk_default_user_rights_list:
        try:
            permission_flag = getattr(PyTalkPermission, right_string.upper())
            pytalk_user_rights |= permission_flag
        except AttributeError:
            logger.warning(
                "Invalid user right string '%s' in provided list. Skipping.",
                right_string,
            )
        except Exception:
            logger.exception("Error processing permission string '%s':", right_string)
    return pytalk_user_rights


async def _send_broadcast_message_directly(
    active_server_instance: TeamTalkInstance, content: str
) -> None:
    """Workaround function to send a broadcast message by calling the SDK directly.

    This fixes the issue on Linux where the string is not correctly encoded.
    """
    try:
        msg = TeamTalk5.TextMessage()
        msg.nMsgType = TeamTalk5.TextMsgType.MSGTYPE_BROADCAST

        if (
            hasattr(active_server_instance, "cached_my_user_id")
            and active_server_instance.cached_my_user_id is not None
        ):
            msg.nFromUserID = active_server_instance.cached_my_user_id
        else:
            logger.warning(
                "Bot UserID not found in cache. Fetching from server (fallback)."
            )
            msg.nFromUserID = active_server_instance.getMyUserID()

        if (
            hasattr(active_server_instance, "cached_my_user_account")
            and active_server_instance.cached_my_user_account
        ):
            my_account = active_server_instance.cached_my_user_account
            msg.szFromUsername = my_account.szUsername
        else:
            logger.warning(
                "Bot UserAccount not found in cache. Fetching from server (fallback)."
            )
            my_account = active_server_instance.getMyUserAccount()
            if my_account:
                msg.szFromUsername = my_account.szUsername
            else:
                logger.error(
                    "Could not retrieve own user account for broadcast message (cache "
                    "and fallback failed). Using default 'Bot'."
                )
                msg.szFromUsername = TeamTalk5.ttstr("Bot")

        msg.nToUserID = 0
        msg.nChannelID = 0
        msg.szMessage = TeamTalk5.ttstr(content)
        msg.bMore = False

        active_server_instance.doTextMessage(msg)
        logger.info("Broadcast message for user sent directly via SDK: '%s'", content)

    except Exception:
        logger.exception("Failed to send broadcast message directly via SDK:")


async def _handle_registration_broadcast(
    active_server_instance: TeamTalkInstance,
    username: str,
    broadcast_message_text: str | None,
    *,
    registration_broadcast_enabled: bool,
) -> None:
    """Handles sending a registration broadcast message if enabled."""
    if not registration_broadcast_enabled:
        logger.info(
            "Registration broadcast is disabled by parameter. Skipping for user '%s'.",
            username,
        )
        return

    if not broadcast_message_text:
        logger.info(
            "No broadcast message text provided for user '%s'. Skipping broadcast.",
            username,
        )
        return

    # Instead of calling the broken library function, we call our direct SDK
    # workaround
    await _send_broadcast_message_directly(
        active_server_instance, broadcast_message_text
    )


# --- Main Functions ---
async def check_username_exists(
    pytalk_bot_instance: pytalk.TeamTalkBot, username: str
) -> bool | None:
    """Checks if a username exists on the TeamTalk server."""
    if not pytalk_bot_instance.teamtalks:
        logger.warning(
            "No active TeamTalk server connections in check_username_exists."
        )
        return None

    active_server_instance = pytalk_bot_instance.teamtalks[0]

    if not active_server_instance.logged_in:
        # Corrected attribute access from .info.host to .server_info.host
        host_display = (
            active_server_instance.server_info.host
            if hasattr(active_server_instance, "server_info")
            and active_server_instance.server_info
            else "Unknown Host"
        )
        logger.warning(
            "Not logged in to TeamTalk server %s in check_username_exists.",
            host_display,
        )
        return None

    try:
        user_accounts_list = await active_server_instance.list_user_accounts()
        for account_obj in user_accounts_list:
            try:
                if account_obj.username.strip().lower() == username.strip().lower():
                    return True
            except AttributeError:
                # This is expected if an object in the list doesn't conform,
                # or if 'username' is not a direct attribute in some cases with
                # pytalk. As per user feedback, no warning log is needed here.
                pass
    except IndexError:
        logger.exception(
            "No active TeamTalk server connections in check_username_exists "
            "(IndexError)."
        )
        return None
    except Exception:
        logger.exception(
            "Error checking username existence for '%s':",
            username,
        )
        return None
    else:
        return False


async def perform_teamtalk_registration(
    pytalk_bot_instance: pytalk.TeamTalkBot,  # New argument
    username_str: str,
    password_str: str,
    usertype_to_create: PyTalkUserType,
    teamtalk_default_user_rights: list[str],
    *,
    registration_broadcast_enabled: bool,
    host_name: str,  # For artefact_data
    tcp_port: int,  # For artefact_data
    udp_port: int,  # For artefact_data
    encrypted: bool,  # For artefact_data
    server_name: str,  # For artefact_data
    teamtalk_public_hostname: str | None,  # For artefact_data
    nickname_str: str | None = None,
    source_info: dict | None = None,
    broadcast_message_text: str | None = None,
) -> tuple[bool, str | None, TeamTalkRegistrationArtefacts | None]:
    """Performs the TeamTalk registration."""
    if not pytalk_bot_instance.teamtalks:
        logger.error(
            "TeamTalk bot (pytalk_bot) has no active server connections for "
            "registration."
        )
        return False, "MODULE_UNAVAILABLE", None

    active_server_instance = pytalk_bot_instance.teamtalks[0]

    if not active_server_instance.logged_in:
        host_display = (
            active_server_instance.server_info.host
            if hasattr(active_server_instance, "server_info")
            and active_server_instance.server_info
            else "Unknown Host"
        )
        logger.error(
            "TeamTalk bot (pytalk_bot_instance) is not logged in to server %s for "
            "registration.",
            host_display,
        )
        return False, "MODULE_UNAVAILABLE", None

    pytalk_user_rights = _calculate_pytalk_user_rights(teamtalk_default_user_rights)

    try:
        final_nickname = (
            nickname_str if nickname_str and nickname_str.strip() else username_str
        )
        logger.info(
            "Attempting to register TT User. Username: '%s', Nickname for "
            "files/links: '%s', Source: %s",
            username_str,
            final_nickname,
            source_info,
        )

        success_from_pytalk = active_server_instance.create_user_account(
            username=username_str,
            password=password_str,
            usertype=usertype_to_create,
            user_rights=pytalk_user_rights,
            note="",  # Note field is available, can be populated from source_info if
            # needed
        )

        if not success_from_pytalk:
            logger.error(
                "PyTalk Registration Error for user %s. create_user_account "
                "returned False.",
                username_str,
            )
            return False, "REG_FAILED_PYTALK", None

        logger.info("User %s registration successful via PyTalk.", username_str)

        await _handle_registration_broadcast(
            active_server_instance,
            username_str,
            broadcast_message_text,
            registration_broadcast_enabled=registration_broadcast_enabled,
        )

        effective_hostname = (
            teamtalk_public_hostname if teamtalk_public_hostname else host_name
        )
        artefact_data = TeamTalkRegistrationArtefacts(
            username=username_str,
            password=password_str,
            final_nickname=final_nickname,
            effective_hostname=effective_hostname,
            server_name=server_name,
            tcp_port=tcp_port,
            udp_port=udp_port,
            encrypted=encrypted,
        )

    except IndexError:  # Should be caught by the initial check, but as a safeguard
        logger.exception(
            "TeamTalk bot (pytalk_bot_instance) has no active server connections "
            "(IndexError) for registration."
        )
        return False, "MODULE_UNAVAILABLE", None
    except Exception:
        logger.exception(
            "General error during SDK registration for user %s:",
            username_str,
        )
        return False, "UNEXPECTED_ERROR", None
    else:
        return True, "REG_SUCCESS", artefact_data
