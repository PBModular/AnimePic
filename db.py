from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase
from sqlalchemy import BigInteger


class Base(DeclarativeBase):
    pass


class ChatState(Base):
    __tablename__ = 'chat_state'
    chat_id: Mapped[int] = mapped_column(primary_key=True)
    rating: Mapped[str] = mapped_column(nullable=True)
    limit: Mapped[int] = mapped_column(nullable=True)
    
    def __repr__(self):
        return f"ChatState(id={self.chat_id}, rating={self.rating})"
