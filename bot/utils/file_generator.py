"""This module contains functions for generating .tt files and links."""
import logging
from urllib.parse import quote_plus

from .schemas import TTConnectionInfo, TTUserInfo

logger = logging.getLogger(__name__)


def generate_tt_file_content(connection: TTConnectionInfo, user: TTUserInfo) -> str:
    """Generates the content for a .tt file based on connection and user info models."""
    encrypted_str_val = "true" if connection.encrypted else "false"
    # Basic XML escaping for username/password in .tt file
    escaped_username = (
        user.username.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    escaped_password = (
        user.password.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

    file_nickname = (
        user.nickname if user.nickname and user.nickname.strip() else user.username
    )
    escaped_nickname = (
        file_nickname.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE teamtalk>
<teamtalk version="5.0">
 <host>
  <name>{connection.server_name}</name>
  <address>{connection.host}</address>
  <tcpport>{connection.tcpport}</tcpport>
  <udpport>{connection.udpport}</udpport>
  <encrypted>{encrypted_str_val}</encrypted>
  <trusted-certificate>
   <certificate-authority-pem></certificate-authority-pem>
   <client-certificate-pem></client-certificate-pem>
   <client-private-key-pem></client-private-key-pem>
   <verify-peer>false</verify-peer>
  </trusted-certificate>
  <auth>
   <username>{escaped_username}</username>
   <password>{escaped_password}</password>
   <nickname>{escaped_nickname}</nickname>
  </auth>
 </host>
</teamtalk>"""


def generate_tt_link(connection: TTConnectionInfo, user: TTUserInfo) -> str:
    """Generates a tt:// quick connect link based on connection and user info models."""
    encrypted_link_val = "1" if connection.encrypted else "0"
    encoded_username = quote_plus(user.username)
    encoded_password = quote_plus(user.password)

    link_nickname = (
        user.nickname if user.nickname and user.nickname.strip() else user.username
    )
    encoded_nickname = quote_plus(link_nickname)

    return f"tt://{connection.host}?tcpport={connection.tcpport}&udpport={connection.udpport}&encrypted={encrypted_link_val}&username={encoded_username}&password={encoded_password}&nickname={encoded_nickname}&channel=/&chanpasswd="
