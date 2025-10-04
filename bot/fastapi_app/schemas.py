from pydantic import BaseModel


class RegistrationPayload(BaseModel):
    username: str
    password: str
    nickname: str | None = None
