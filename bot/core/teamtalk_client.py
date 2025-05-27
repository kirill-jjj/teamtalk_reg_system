import logging
import pytalk
from pytalk.enums import TeamTalkServerInfo as PyTalkServerInfo
from pytalk.message import Message as PyTalkMessage
from typing import Optional, Tuple, Dict, TYPE_CHECKING

from . import config
from .localization import get_tg_strings, get_admin_lang_code
from ..utils.file_generator import generate_tt_file_content, generate_tt_link

if TYPE_CHECKING:
    from aiogram import Bot as AiogramBot

logger = logging.getLogger(__name__)

# Global SDK Objects - initialized in on_ready
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

# В начале файла bot/core/teamtalk_client.py, если еще не импортировано:
from typing import Optional 
# ... (остальные импорты)

async def check_username_exists(username: str) -> Optional[bool]: # Изменен тип возвращаемого значения
    if not TeamTalkSDK or not ttstr_sdk:
        logger.error("TeamTalk SDK not initialized in check_username_exists.")
        return None # Ошибка, а не "имя занято"

    try:
        if not pytalk_bot.teamtalks: # Проверяем, существует ли список и он не пуст
            logger.warning("No active TeamTalk server connections in check_username_exists (teamtalks list is empty).")
            return None # Ошибка

        # Предполагаем, что используется первое (или единственное) соединение
        active_server_instance = pytalk_bot.teamtalks[0] 
        
        if not active_server_instance.logged_in:
            logger.warning(f"Not logged in to TeamTalk server {active_server_instance.info.host} in check_username_exists.")
            return None # Ошибка

        user_accounts_sdk_list = await active_server_instance.list_user_accounts() # Вызов у экземпляра сервера

        for account_pytalk_obj in user_accounts_sdk_list:
            # Check if the object from pytalk has the underlying SDK structure
            # This depends on pytalk's implementation details
            if hasattr(account_pytalk_obj, '_account') and hasattr(account_pytalk_obj._account, 'szUsername'):
                existing_username_bytes = account_pytalk_obj._account.szUsername
                existing_username = ttstr_sdk(existing_username_bytes) # Use ttstr_sdk for conversion
                if existing_username.strip().lower() == username.strip().lower():
                    return True # Имя занято
            else:
                # Fallback for older pytalk or different structure
                # Or if pytalk directly returns string usernames in its objects
                if hasattr(account_pytalk_obj, 'username') and isinstance(account_pytalk_obj.username, str):
                    if account_pytalk_obj.username.strip().lower() == username.strip().lower():
                        return True # Имя занято
                else:
                    logger.warning(f"UserAccount object {type(account_pytalk_obj)} from pytalk doesn't have expected SDK structure or direct username attribute.")
        return False # Имя свободно
    except IndexError: # Если pytalk_bot.teamtalks[0] вызовет IndexError (список пуст после первой проверки)
        logger.error("No active TeamTalk server connections in check_username_exists (IndexError).")
        return None # Ошибка
    except Exception as e:
        logger.error(f"Error checking username existence for '{username}': {e}")
        return None # Ошибка

async def perform_teamtalk_registration(
    username_str: str,
    password_str: str,
    source_info: Optional[Dict] = None,
    aiogram_bot_instance: Optional['AiogramBot'] = None # Pass the bot instance for notifications
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:

    if not TeamTalkSDK or not ttstr_sdk:
        logger.error("TeamTalk SDK (TeamTalkSDK or ttstr_sdk) not initialized for registration.")
        return False, "MODULE_UNAVAILABLE", None, None

    if not pytalk_bot.teamtalks or not pytalk_bot.teamtalks.logged_in:
        logger.error("TeamTalk bot (pytalk_bot) is not connected to any server for registration.")
        return False, "MODULE_UNAVAILABLE", None, None

    tt_instance_raw_sdk = pytalk_bot.teamtalks._tt # Access underlying SDK instance from pytalk

    # SDK Enums and Classes
    UserRight = TeamTalkSDK.UserRight
    UserAccount = TeamTalkSDK.UserAccount
    SDKUserType = TeamTalkSDK.UserType
    TextMessage = TeamTalkSDK.TextMessage
    TextMsgType = TeamTalkSDK.TextMsgType

    # Define user rights
    custom_user_rights = (
        UserRight.USERRIGHT_MULTI_LOGIN | UserRight.USERRIGHT_VIEW_ALL_USERS |
        UserRight.USERRIGHT_CREATE_TEMPORARY_CHANNEL | UserRight.USERRIGHT_UPLOAD_FILES |
        UserRight.USERRIGHT_DOWNLOAD_FILES | UserRight.USERRIGHT_TRANSMIT_VOICE |
        UserRight.USERRIGHT_TRANSMIT_VIDEOCAPTURE | UserRight.USERRIGHT_TRANSMIT_DESKTOP |
        UserRight.USERRIGHT_TRANSMIT_DESKTOPINPUT | UserRight.USERRIGHT_TRANSMIT_MEDIAFILE |
        UserRight.USERRIGHT_TEXTMESSAGE_USER | UserRight.USERRIGHT_TEXTMESSAGE_CHANNEL
    )

    try:
        logger.info(f"Attempting to register TT User. Username: '{username_str}', Source: {source_info}")
        user_account_obj = UserAccount()
        user_account_obj.szUsername = ttstr_sdk(username_str)
        user_account_obj.szPassword = ttstr_sdk(password_str)
        user_account_obj.uUserType = SDKUserType.USERTYPE_DEFAULT
        user_account_obj.uUserRights = custom_user_rights
        # user_account_obj.szNote = ttstr_sdk(source_info.get("note", "")) # Example if you add notes

        # Directly use the SDK function for creating a new user account
        result_code_cmd_id = TeamTalkSDK._DoNewUserAccount(tt_instance_raw_sdk, user_account_obj)
        
        # _DoNewUserAccount returns a command ID or -1 on client-side error.
        # We need to wait for CMD_SUCCESS or CMD_ERROR for this command ID.
        # Pytalk might handle this internally, or we might need to listen for it.
        # For now, assume direct SDK call style like in original botreg.py
        # If pytalk has a higher-level wrapper, that would be preferred.

        if result_code_cmd_id == -1: # Client-side error before sending to server
            logger.error(f"SDK Client-Side Registration Error for user {username_str}. cmdID: {result_code_cmd_id}.")
            return False, "REG_FAILED_SDK_CLIENT", None, None

        # Here, you'd ideally wait for a CMD_SUCCESS or CMD_ERROR event for result_code_cmd_id.
        # The original code assumed success if cmdID wasn't -1, which might not be robust.
        # Pytalk's create_user_account might handle this wait. If using direct SDK, more complex event handling is needed.
        # For simplicity and mimicking original logic here, we'll proceed, but this is a point for improvement.
        logger.info(f"User {username_str} registration command sent to server (cmdID: {result_code_cmd_id}). Assuming eventual success or failure via server events.")


        # Broadcast message after successful registration attempt
        try:
            # Use admin's preferred language for broadcast on TeamTalk server
            admin_lang_code = get_admin_lang_code()
            broadcast_s = get_tg_strings(admin_lang_code) # Re-using TG strings for TT broadcast
            broadcast_text_tt = broadcast_s["admin_broadcast_user_registered_tt"].format(username_str)

            broadcast_message_sdk_obj = TextMessage()
            broadcast_message_sdk_obj.nMsgType = TextMsgType.MSGTYPE_BROADCAST
            broadcast_message_sdk_obj.szMessage = ttstr_sdk(broadcast_text_tt)
            TeamTalkSDK._DoTextMessage(tt_instance_raw_sdk, broadcast_message_sdk_obj)
            logger.info(f"Broadcast message for user '{username_str}' sent to server.")
        except Exception as e_broadcast:
            logger.error(f"Failed to send broadcast message for user '{username_str}': {e_broadcast}")

        # Admin notifications via Telegram
        if aiogram_bot_instance and config.ADMIN_IDS and source_info:
            admin_notify_s = get_tg_strings(get_admin_lang_code()) # Admin's language for Telegram
            
            admin_notification_message = f"📢 {admin_notify_s['admin_broadcast_user_registered_tt'].format(username_str)}\n"
            
            reg_type = source_info.get('type', 'Unknown')
            user_client_lang_code_for_source = source_info.get('user_lang', 'en') # Language of the user who registered
            lang_emoji = "🇬🇧" if user_client_lang_code_for_source == 'en' else "🇷🇺"
            admin_notification_message += f"👤 Язык клиента: {lang_emoji}\n"

            if reg_type == 'telegram':
                tg_user_id_val = source_info.get('telegram_id', 'N/A')
                tg_full_name_val = source_info.get('telegram_full_name', 'N/A')
                admin_notification_message += f"📱 Через Telegram: {tg_full_name_val} (ID: {tg_user_id_val})\n"
            elif reg_type == 'web':
                ip_address_val = source_info.get('ip_address', 'N/A')
                admin_notification_message += f"🌐 Через Web: IP {ip_address_val}\n"
            
            for admin_id_val_notify in config.ADMIN_IDS:
                try:
                    await aiogram_bot_instance.send_message(admin_id_val_notify, admin_notification_message.strip())
                except Exception as e_admin_notify:
                    logger.error(f"Failed to send admin notification to {admin_id_val_notify}: {e_admin_notify}")
        
        # Generate .tt file and link
        tt_file_content_val = generate_tt_file_content(
            config.SERVER_NAME, config.HOST_NAME, config.TCP_PORT, config.UDP_PORT,
            config.ENCRYPTED, username_str, password_str
        )
        tt_link_val = generate_tt_link(
            config.HOST_NAME, config.TCP_PORT, config.UDP_PORT,
            config.ENCRYPTED, username_str, password_str
        )
        # Assuming success here as per original logic. Robust implementation would confirm with CMD_SUCCESS.
        return True, "REG_SUCCESS", tt_file_content_val, tt_link_val

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
        await pytalk_bot.add_server(server_info_pytalk) # This internally connects and logs in
        # Assuming add_server appends the instance and we're interested in the last added one.
        # Also ensure teamtalks is not empty before accessing.
        if pytalk_bot.teamtalks and pytalk_bot.teamtalks[-1].logged_in:
            logger.info(f"Successfully connected and logged into TeamTalk server: {config.HOST_NAME}")
            if await initialize_sdk_objects(): # Initialize SDK objects after connection
                 return True
            else:
                 return False # SDK init failed
        else:
            # Log more details if teamtalks is empty or last instance is not logged in
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
    # Pytalk's __aexit__ should handle disconnection, but explicit calls can be added if needed.
    logger.info("Shutting down PyTalk bot connections.")
    # Example: Explicitly logging out and disconnecting if pytalk_bot.close() isn't enough
    for tt_instance in pytalk_bot.teamtalks:
        if tt_instance.logged_in:
            tt_instance.logout()
        if tt_instance.connected:
            tt_instance.disconnect()
        # tt_instance.closeTeamTalk() # Pytalk might do this in its cleanup
    pytalk_bot.teamtalks.clear()