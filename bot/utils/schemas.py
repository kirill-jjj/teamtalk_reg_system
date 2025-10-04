from pydantic import BaseModel


class TTConnectionInfo(BaseModel):
    server_name: str
    host: str
    tcpport: int
    udpport: int
    encrypted: bool


class TTUserInfo(BaseModel):
    username: str
    password: str
    nickname: str | None = None
