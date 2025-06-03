import logging
import pytalk
from pytalk.enums import TeamTalkServerInfo as PyTalkServerInfo
from pytalk.message import Message as PyTalkMessage
from typing import Optional, Tuple, Dict, TYPE_CHECKING

from . import config
from .localization import get_translator, get_admin_lang_code
from ..utils.file_generator import generate_tt_file_content, generate_tt_link

if TYPE_CHECKING:
    from aiogram import Bot as AiogramBot

logger = logging.getLogger(__name__)

# Global SDK Objects
TeamTalkSDK = None
ttstr_sdk = None

# PyTalk Bot Instance
pytalk_bot = pytalk.TeamTalkBot(client_name=config.CLIENT_NAME)

async def initialize_sdk_objects():
    global TeamTalkSDK, ttstr_sdk
    if pytalk_bot.teamtalks and hasattr(pytalk_bot.teamtalks[-1], '_tt') and pytalk_bot.teamtalks[-1]._tt:
        TeamTalkSDK = pytalk.sdk
        ttstr_sdk = TeamTalkSDK.ttstr
        logger.info("TeamTalk SDK object and ttstr initialized globally from core client.")
        return True
    else:
        if not pytalk_bot.teamtalks:
            logger.error("Failed to initialize TeamTalk SDK: pytalk_bot.teamtalks list is empty.")
        elif not hasattr(pytalk_bot.teamtalks[-1], '_tt'):
            logger.error("Failed to initialize TeamTalk SDK: Last server instance in pytalk_bot.teamtalks does not have '_tt' attribute.")
        elif not pytalk_bot.teamtalks[-1]._tt:
            logger.error("Failed to initialize TeamTalk SDK: Last server instance's '_tt' attribute is None or False.")
        else:
            logger.error("Failed to initialize TeamTalk SDK object: No active server connection in pytalk_bot or _tt is not available for an unknown reason.")
        return False

async def check_username_exists(username: str) -> Optional[bool]:
    if not TeamTalkSDK or not ttstr_sdk:
        logger.error("TeamTalk SDK not initialized in check_username_exists.")
        return None 

    try:
        if not pytalk_bot.teamtalks: 
            logger.warning("No active TeamTalk server connections in check_username_exists (teamtalks list is empty).")
            return None 

        active_server_instance = pytalk_bot.teamtalks[0] 
        
        if not active_server_instance.logged_in:
            logger.warning(f"Not logged in to TeamTalk server {active_server_instance.info.host} in check_username_exists.")
            return None 

        user_accounts_sdk_list = await active_server_instance.list_user_accounts() 

        for account_pytalk_obj in user_accounts_sdk_list:
            if hasattr(account_pytalk_obj, '_account') and hasattr(account_pytalk_obj._account, 'szUsername'):
                existing_username_bytes = account_pytalk_obj._account.szUsername
                existing_username = ttstr_sdk(existing_username_bytes) 
                if existing_username.strip().lower() == username.strip().lower():
                    return True 
            else:
                if hasattr(account_pytalk_obj, 'username') and isinstance(account_pytalk_obj.username, str):
                    if account_pytalk_obj.username.strip().lower() == username.strip().lower():
                        return True 
                else:
                    logger.warning(f"UserAccount object {type(account_pytalk_obj)} from pytalk doesn't have expected SDK structure or direct username attribute.")
        return False 
    except IndexError: 
        logger.error("No active TeamTalk server connections in check_username_exists (IndexError).")
        return None 
    except Exception as e:
        logger.error(f"Error checking username existence for '{username}': {e}")
        return None 

async def perform_teamtalk_registration(
    username_str: str,
    password_str: str,
    nickname_str: Optional[str] = None, # Added
    source_info: Optional[Dict] = None,
    aiogram_bot_instance: Optional['AiogramBot'] = None 
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:

    if not TeamTalkSDK or not ttstr_sdk:
        logger.error("TeamTalk SDK (TeamTalkSDK or ttstr_sdk) not initialized for registration.")
        return False, "MODULE_UNAVAILABLE", None, None

    if not pytalk_bot.teamtalks: 
        logger.error("TeamTalk bot (pytalk_bot) has no active server connections (teamtalks list is empty) for registration.")
        return False, "MODULE_UNAVAILABLE", None, None
    
    active_server_instance = pytalk_bot.teamtalks[0]

    if not active_server_instance.logged_in:
        logger.error(f"TeamTalk bot (pytalk_bot) is not logged in to server {active_server_instance.info.host} for registration.")
        return False, "MODULE_UNAVAILABLE", None, None

    tt_instance_raw_sdk = active_server_instance._tt

    UserRight = TeamTalkSDK.UserRight
    UserAccount = TeamTalkSDK.UserAccount
    SDKUserType = TeamTalkSDK.UserType
    TextMessage = TeamTalkSDK.TextMessage
    TextMsgType = TeamTalkSDK.TextMsgType

    custom_user_rights = (
        UserRight.USERRIGHT_MULTI_LOGIN | UserRight.USERRIGHT_VIEW_ALL_USERS |
        UserRight.USERRIGHT_CREATE_TEMPORARY_CHANNEL | UserRight.USERRIGHT_UPLOAD_FILES |
        UserRight.USERRIGHT_DOWNLOAD_FILES | UserRight.USERRIGHT_TRANSMIT_VOICE |
        UserRight.USERRIGHT_TRANSMIT_VIDEOCAPTURE | UserRight.USERRIGHT_TRANSMIT_DESKTOP |
        UserRight.USERRIGHT_TRANSMIT_DESKTOPINPUT | UserRight.USERRIGHT_TRANSMIT_MEDIAFILE |
        UserRight.USERRIGHT_TEXTMESSAGE_USER | UserRight.USERRIGHT_TEXTMESSAGE_CHANNEL
    )

    try:
        # final_nickname is for .tt files and links, not for the server account itself.
        final_nickname = nickname_str if nickname_str and nickname_str.strip() else username_str
        logger.info(f"Attempting to register TT User. Username: '{username_str}', Nickname for files/links: '{final_nickname}', Source: {source_info}")
        user_account_obj = UserAccount()
        user_account_obj.szUsername = ttstr_sdk(username_str)
        user_account_obj.szPassword = ttstr_sdk(password_str)

        # Nickname for the TeamTalk server account will always be the same as the username.
        # The custom nickname (if any, from nickname_str / final_nickname) is used for .tt files and links only.
        logger.info(f"Setting TeamTalk server account nickname for '{username_str}' to be the same as the username.")
        user_account_obj.szNickname = ttstr_sdk(username_str) # Explicitly set to username for server account

        user_account_obj.uUserType = SDKUserType.USERTYPE_DEFAULT
        user_account_obj.uUserRights = custom_user_rights

        result_code_cmd_id = TeamTalkSDK._DoNewUserAccount(tt_instance_raw_sdk, user_account_obj)
        
        if result_code_cmd_id == -1: 
            logger.error(f"SDK Client-Side Registration Error for user {username_str}. cmdID: {result_code_cmd_id}.")
            return False, "REG_FAILED_SDK_CLIENT", None, None

        logger.info(f"User {username_str} registration command sent to server (cmdID: {result_code_cmd_id}). Assuming eventual success or failure via server events.")

        try:
            admin_lang_code = get_admin_lang_code()
            _ = get_translator(admin_lang_code) 
            broadcast_text_tt = _("User {} was registered.").format(username_str)

            broadcast_message_sdk_obj = TextMessage()
            broadcast_message_sdk_obj.nMsgType = TextMsgType.MSGTYPE_BROADCAST
            broadcast_message_sdk_obj.szMessage = ttstr_sdk(broadcast_text_tt)
            TeamTalkSDK._DoTextMessage(tt_instance_raw_sdk, broadcast_message_sdk_obj)
            logger.info(f"Broadcast message for user '{username_str}' sent to server.")
        except Exception as e_broadcast:
            logger.error(f"Failed to send broadcast message for user '{username_str}': {e_broadcast}")

        if aiogram_bot_instance and config.ADMIN_IDS and source_info:
            _admin_tg = get_translator(get_admin_lang_code()) 
            
            admin_notification_message = f"📢 {_admin_tg('User {} was registered.').format(username_str)}\n"
            
            reg_type = source_info.get('type', 'Unknown')
            user_client_lang_code_for_source = source_info.get('user_lang', 'en') 
            lang_emoji = "🇬🇧" if user_client_lang_code_for_source == 'en' else "🇷🇺"
            admin_notification_message += _admin_tg("👤 Client language: {}").format(lang_emoji) + "\n"

            if reg_type == 'telegram':
                tg_user_id_val = source_info.get('telegram_id', 'N/A')
                tg_full_name_val = source_info.get('telegram_full_name', 'N/A')
                admin_notification_message += _admin_tg("📱 Via Telegram: {} (ID: {})").format(tg_full_name_val, tg_user_id_val) + "\n"
            elif reg_type == 'web':
                ip_address_val = source_info.get('ip_address', 'N/A')
                admin_notification_message += _admin_tg("🌐 Via Web: IP {}").format(ip_address_val) + "\n"
            
            for admin_id_val_notify in config.ADMIN_IDS:
                try:
                    await aiogram_bot_instance.send_message(admin_id_val_notify, admin_notification_message.strip())
                except Exception as e_admin_notify:
                    logger.error(f"Failed to send admin notification to {admin_id_val_notify}: {e_admin_notify}")
        
        tt_file_content_val = generate_tt_file_content(
            config.SERVER_NAME, config.HOST_NAME, config.TCP_PORT, config.UDP_PORT,
            config.ENCRYPTED, username_str, password_str,
            final_nickname # Added
        )
        tt_link_val = generate_tt_link(
            config.HOST_NAME, config.TCP_PORT, config.UDP_PORT,
            config.ENCRYPTED, username_str, password_str,
            final_nickname # Added
        )
        return True, "REG_SUCCESS", tt_file_content_val, tt_link_val

    except IndexError: 
        logger.error("TeamTalk bot (pytalk_bot) has no active server connections (IndexError) for registration.")
        return False, "MODULE_UNAVAILABLE", None, None
    except Exception as e_reg:
        logger.exception(f"General error during SDK registration for user {username_str}: {e_reg}")
        return False, f"UNEXPECTED_ERROR:{str(e_reg)}", None, None

async def connect_to_teamtalk_server():
    server_info_pytalk = PyTalkServerInfo(
        host=config.HOST_NAME,
        tcp_port=config.TCP_PORT,
        udp_port=config.UDP_PORT,
        username=config.USER_NAME,
        password=config.PASSWORD,
        nickname=config.NICK_NAME,
        encrypted=config.ENCRYPTED
    )
    try:
        await pytalk_bot.add_server(server_info_pytalk) 
        if pytalk_bot.teamtalks and pytalk_bot.teamtalks[-1].logged_in:
            logger.info(f"Successfully connected and logged into TeamTalk server: {config.HOST_NAME}")
            if await initialize_sdk_objects(): 
                 return True
            else:
                 return False 
        else:
            if not pytalk_bot.teamtalks:
                logger.error(f"Failed to connect or login: pytalk_bot.teamtalks list is empty after add_server for {config.HOST_NAME}.")
            elif not pytalk_bot.teamtalks[-1].logged_in:
                 logger.error(f"Failed to connect or login: Last server instance for {config.HOST_NAME} is not logged_in.")
            else:
                 logger.error(f"Failed to connect or login to TeamTalk server: {config.HOST_NAME} via PyTalk for an unknown reason.")
            return False
    except Exception as e:
        logger.error(f"Error adding/connecting to TeamTalk server via PyTalk: {e}", exc_info=True)
        return False

async def shutdown_pytalk_bot():
    logger.info("Shutting down PyTalk bot connections.")
    for tt_instance in pytalk_bot.teamtalks:
        if tt_instance.logged_in:
            tt_instance.logout()
        if tt_instance.connected:
            tt_instance.disconnect()
    pytalk_bot.teamtalks.clear()