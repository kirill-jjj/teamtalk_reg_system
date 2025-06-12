import logging
from typing import Optional, Tuple, Dict, Any, List # Added List

import pytalk
from pytalk.enums import UserType as PyTalkUserType
from pytalk.permission import Permission as PyTalkPermission
from pytalk.instance import TeamTalkInstance
from pytalk.implementation.TeamTalkPy import TeamTalk5 as sdk

from .connection import pytalk_bot

logger = logging.getLogger(__name__)

# --- Helper Functions ---
def _calculate_pytalk_user_rights(teamtalk_default_user_rights_list: List[str]) -> int:
    """Calculates the PyTalk user rights bitmask from the provided list."""
    pytalk_user_rights = 0
    for right_string in teamtalk_default_user_rights_list:
        try:
            permission_flag = getattr(PyTalkPermission, right_string.upper())
            pytalk_user_rights |= permission_flag
        except AttributeError:
            logger.warning(f"Invalid user right string '{right_string}' in provided list. Skipping.")
        except Exception as e_perm:
            logger.error(f"Error processing permission string '{right_string}': {e_perm}")
    return pytalk_user_rights

async def _send_broadcast_message_directly(active_server_instance: TeamTalkInstance, content: str):
    """
    Workaround function to send a broadcast message by calling the SDK directly.
    This fixes the issue on Linux where the string is not correctly encoded.
    """
    try:
        msg = sdk.TextMessage()
        msg.nMsgType = sdk.TextMsgType.MSGTYPE_BROADCAST
        msg.nFromUserID = active_server_instance.getMyUserID()

        my_account = active_server_instance.getMyUserAccount()

        if my_account:
            msg.szFromUsername = my_account.szUsername
        else:
            logger.warning("Could not retrieve own user account for broadcast message sender username. Using default 'Bot'.")
            msg.szFromUsername = sdk.ttstr("Bot")

        msg.nToUserID = 0
        msg.nChannelID = 0
        msg.szMessage = sdk.ttstr(content)
        msg.bMore = False

        active_server_instance.doTextMessage(msg)
        logger.info(f"Broadcast message for user sent directly via SDK: '{content}'")

    except Exception as e:
        logger.error(f"Failed to send broadcast message directly via SDK: {e}", exc_info=True)


async def _handle_registration_broadcast(
    active_server_instance: TeamTalkInstance,
    username: str,
    broadcast_message_text: Optional[str],
    registration_broadcast_enabled: bool
):
    '''Handles sending a registration broadcast message if enabled and message provided.'''
    if not registration_broadcast_enabled:
        logger.info(f"Registration broadcast is disabled by parameter. Skipping for user '{username}'.")
        return

    if not broadcast_message_text:
        logger.info(f"No broadcast message text provided for user '{username}'. Skipping broadcast.")
        return

    # Instead of calling the broken library function, we call our direct SDK workaround
    await _send_broadcast_message_directly(active_server_instance, broadcast_message_text)

# --- Main Functions ---
async def check_username_exists(username: str) -> Optional[bool]:
    if not pytalk_bot.teamtalks:
        logger.warning("No active TeamTalk server connections in check_username_exists.")
        return None

    active_server_instance = pytalk_bot.teamtalks[0]

    if not active_server_instance.logged_in:
        # Corrected attribute access from .info.host to .server_info.host
        host_display = active_server_instance.server_info.host if hasattr(active_server_instance, 'server_info') and active_server_instance.server_info else "Unknown Host"
        logger.warning(f"Not logged in to TeamTalk server {host_display} in check_username_exists.")
        return None

    try:
        user_accounts_list = await active_server_instance.list_user_accounts()
        for account_obj in user_accounts_list:
            try:
                if account_obj.username.strip().lower() == username.strip().lower():
                    return True
            except AttributeError:
                # This is expected if an object in the list doesn't conform,
                # or if 'username' is not a direct attribute in some cases with pytalk.
                # As per user feedback, no warning log is needed here.
                pass
        return False
    except IndexError:
        logger.error("No active TeamTalk server connections in check_username_exists (IndexError).")
        return None
    except Exception as e:
        logger.error(f"Error checking username existence for '{username}': {e}", exc_info=True)
        return None

async def perform_teamtalk_registration(
    username_str: str,
    password_str: str,
    usertype_to_create: PyTalkUserType,
    teamtalk_default_user_rights: List[str],
    registration_broadcast_enabled: bool,
    host_name: str, # For artefact_data
    tcp_port: int,  # For artefact_data
    udp_port: int,  # For artefact_data
    encrypted: bool,# For artefact_data
    server_name: str,# For artefact_data
    teamtalk_public_hostname: Optional[str],# For artefact_data
    nickname_str: Optional[str] = None,
    source_info: Optional[Dict] = None,
    broadcast_message_text: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:

    if not pytalk_bot.teamtalks:
        logger.error("TeamTalk bot (pytalk_bot) has no active server connections for registration.")
        return False, "MODULE_UNAVAILABLE", None

    active_server_instance = pytalk_bot.teamtalks[0]

    if not active_server_instance.logged_in:
        host_display = active_server_instance.server_info.host if hasattr(active_server_instance, 'server_info') and active_server_instance.server_info else "Unknown Host"
        logger.error(f"TeamTalk bot (pytalk_bot) is not logged in to server {host_display} for registration.")
        return False, "MODULE_UNAVAILABLE", None

    pytalk_user_rights = _calculate_pytalk_user_rights(teamtalk_default_user_rights)

    try:
        final_nickname = nickname_str if nickname_str and nickname_str.strip() else username_str
        logger.info(f"Attempting to register TT User. Username: '{username_str}', Nickname for files/links: '{final_nickname}', Source: {source_info}")

        success_from_pytalk = active_server_instance.create_user_account(
            username=username_str,
            password=password_str,
            usertype=usertype_to_create,
            user_rights=pytalk_user_rights,
            note="" # Note field is available, can be populated from source_info if needed
        )

        if not success_from_pytalk:
            logger.error(f"PyTalk Registration Error for user {username_str}. create_user_account returned False.")
            return False, "REG_FAILED_PYTALK", None

        logger.info(f"User {username_str} registration successful via PyTalk.")

        await _handle_registration_broadcast(active_server_instance, username_str, broadcast_message_text, registration_broadcast_enabled)

        effective_hostname = teamtalk_public_hostname if teamtalk_public_hostname else host_name
        artefact_data = {
            "username": username_str,
            "password": password_str,
            "final_nickname": final_nickname,
            "effective_hostname": effective_hostname,
            "server_name": server_name,
            "tcp_port": tcp_port,
            "udp_port": udp_port,
            "encrypted": encrypted
        }

        return True, "REG_SUCCESS", artefact_data

    except IndexError: # Should be caught by the initial check, but as a safeguard
        logger.error("TeamTalk bot (pytalk_bot) has no active server connections (IndexError) for registration.")
        return False, "MODULE_UNAVAILABLE", None
    except Exception as e_reg:
        logger.exception(f"General error during SDK registration for user {username_str}: {e_reg}")
        return False, f"UNEXPECTED_ERROR:{str(e_reg)}", None
