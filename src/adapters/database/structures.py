from sqlalchemy import ForeignKey, String, Text, DateTime, Boolean, Index, BigInteger, LargeBinary, Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime
from typing import List, Optional

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    ecdsa_public_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ecdh_public_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ecdh_signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(default=datetime.utcnow)
    online: Mapped[bool] = mapped_column(default=False)

    sent_messages: Mapped[List["Message"]] = relationship(
        "Message",
        foreign_keys="Message.sender_id",
        back_populates="sender"
    )
    received_messages: Mapped[List["Message"]] = relationship(
        "Message",
        foreign_keys="Message.recipient_id",
        back_populates="recipient"
    )

    sent_requests: Mapped[List["ContactRequest"]] = relationship(
        "ContactRequest",
        foreign_keys="ContactRequest.sender_id",
        back_populates="sender"
    )
    received_requests: Mapped[List["ContactRequest"]] = relationship(
        "ContactRequest",
        foreign_keys="ContactRequest.receiver_id",
        back_populates="receiver"
    )

class ContactRequest(Base):
    __tablename__ = "contact_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sender: Mapped["User"] = relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="sent_requests"
    )
    receiver: Mapped["User"] = relationship(
        "User",
        foreign_keys=[receiver_id],
        back_populates="received_requests"
    )

    __table_args__ = (
        Index('ix_unique_request', 'sender_id', 'receiver_id', unique=True),
    )

class Message(Base):
    __tablename__ = "messages"

    __table_args__ = (
        Index('ix_messages_is_delivered', 'is_delivered'),
        Index('ix_messages_recipient_delivered', 'recipient_id', 'is_delivered'),
        Index('ix_messages_sender_timestamp', 'sender_id', 'timestamp'),
        Index('ix_messages_recipient_timestamp', 'recipient_id', 'timestamp'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str]
    content_type: Mapped[Optional[str]]
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    is_delivered: Mapped[bool] = mapped_column(default=False)
    ephemeral_public_key: Mapped[str]
    ephemeral_signature: Mapped[str]

    sender: Mapped["User"] = relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="sent_messages"
    )
    recipient: Mapped["User"] = relationship(
        "User",
        foreign_keys=[recipient_id],
        back_populates="received_messages"
    )

