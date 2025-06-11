from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String

class Base(DeclarativeBase):
    pass

class TelegramRegistration(Base):
    __tablename__ = "telegram_registrations"

    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    teamtalk_username: Mapped[str] = mapped_column(String, nullable=False, unique=True)
