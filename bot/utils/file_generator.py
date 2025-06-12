import os
import secrets
import string
import configparser
import io
from zipfile import ZipFile, ZIP_DEFLATED
from urllib.parse import quote_plus
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


# --- .tt file and TT link generation (retained for now, assuming used by other bot parts) ---
def generate_tt_file_content(
    server_name_val: str, host_val: str, tcpport_val: int, udpport_val: int,
    encrypted_val: bool, username_val: str, password_val: str,
    nickname_val: Optional[str] = None
) -> str:
    encrypted_str_val = "true" if encrypted_val else "false"
    # Basic XML escaping for username/password in .tt file
    escaped_username = username_val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")
    escaped_password = password_val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")

    file_nickname = nickname_val if nickname_val and nickname_val.strip() else username_val
    escaped_nickname = file_nickname.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")

    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE teamtalk>
<teamtalk version="5.0">
 <host>
  <name>{server_name_val}</name>
  <address>{host_val}</address>
  <tcpport>{tcpport_val}</tcpport>
  <udpport>{udpport_val}</udpport>
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

def generate_tt_link(
    host_val: str, tcpport_val: int, udpport_val: int,
    encrypted_val: bool, username_val: str, password_val: str,
    nickname_val: Optional[str] = None
) -> str:
    encrypted_link_val = "1" if encrypted_val else "0"
    encoded_username = quote_plus(username_val)
    encoded_password = quote_plus(password_val)

    link_nickname = nickname_val if nickname_val and nickname_val.strip() else username_val
    encoded_nickname = quote_plus(link_nickname)

    return f"tt://{host_val}?tcpport={tcpport_val}&udpport={udpport_val}&encrypted={encrypted_link_val}&username={encoded_username}&password={encoded_password}&nickname={encoded_nickname}&channel=/&chanpasswd="