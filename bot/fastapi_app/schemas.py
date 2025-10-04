from pydantic import BaseModel


class RegistrationPayload(BaseModel):
    username: str
    password: str
    nickname: str | None = None


class TeamTalkRegistrationArtefacts(BaseModel):
    username: str
    password: str
    final_nickname: str
    effective_hostname: str
    server_name: str
    tcp_port: int
    udp_port: int
    encrypted: bool