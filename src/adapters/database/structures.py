from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ContactStatusEnum(StrEnum):
    BLANK = "blank"
    PENDING = "pending"
    ACCEPTED = "accepted"
    BLACKLIST = "blacklist"


class ChatEventTypeEnum(StrEnum):
    CREATED = "created"
    MEMBER_ADDED = "member_added"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    MEMBER_REMOVED = "member_removed"
    NAME_CHANGED = "name_changed"


class FileTransferStatusEnum(StrEnum):
    UPLOADING = "uploading"
    COMPLETED = "completed"
    DELIVERED = "delivered"


class MessageContentTypeEnum(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    ARCHIVE = "archive"
    CODE = "code"
    OTHER = "other"


class MessageContentMimeTypeEnum(StrEnum):
    TEXT = ".txt"

    JPEG = ".jpeg"
    PNG = ".png"
    GIF = ".gif"
    WEBP = ".webp"
    SVG = ".svg"
    BMP = ".bmp"
    TIFF = ".tiff"
    AVIF = ".avif"
    HEIC = ".heic"

    MP4 = ".mp4"
    WEBM = ".webm"
    AVI = ".avi"
    MOV = ".mov"
    MKV = ".mkv"
    MPEG = ".mpeg"
    OGV = ".ogv"

    MP3 = ".mp3"
    WAV = ".wav"
    OGG = ".ogg"
    AAC = ".aac"
    M4A = ".m4a"
    OPUS = ".opus"
    FLAC = ".flac"

    PDF = ".pdf"
    DOC = ".doc"
    DOCX = ".docx"
    XLS = ".xls"
    XLSX = ".xlsx"
    PPT = ".ppt"
    PPTX = ".pptx"

    ZIP = ".zip"
    RAR = ".rar"
    TAR = ".tar"
    GZIP = ".gz"
    SEVEN_Z = ".7z"

    JSON = ".json"
    XML = ".xml"
    PYTHON = ".py"
    JS = ".js"
    HTML = ".html"
    CSS = ".css"

    BINARY = ".bin"
    MARKDOWN = ".md"
    CSV = ".csv"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    ed_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ecdh_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ecdh_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    online: Mapped[bool] = mapped_column(default=False)

    sent_messages: Mapped[list["Message"]] = relationship(
        "Message", foreign_keys="Message.sender_id", back_populates="sender"
    )
    received_messages: Mapped[list["Message"]] = relationship(
        "Message", foreign_keys="Message.recipient_id", back_populates="recipient"
    )

    sent_requests: Mapped[list["Contact"]] = relationship(
        "Contact",
        foreign_keys="Contact.sender_id",
        back_populates="sender",
    )
    received_requests: Mapped[list["Contact"]] = relationship(
        "Contact",
        foreign_keys="Contact.receiver_id",
        back_populates="receiver",
    )
    created_chats: Mapped[list["Chat"]] = relationship(
        "Chat",
        foreign_keys="Chat.owner_id",
        back_populates="owner",
    )
    chat_memberships: Mapped[list["ChatParticipant"]] = relationship(
        "ChatParticipant",
        foreign_keys="ChatParticipant.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    performed_chat_events: Mapped[list["ChatEvent"]] = relationship(
        "ChatEvent",
        foreign_keys="ChatEvent.actor_id",
        back_populates="actor",
    )
    targeted_chat_events: Mapped[list["ChatEvent"]] = relationship(
        "ChatEvent",
        foreign_keys="ChatEvent.target_user_id",
        back_populates="target_user",
    )

    @property
    def chats(self) -> list["Chat"]:
        return [membership.chat for membership in self.chat_memberships]


class Contact(Base):
    __tablename__ = "contact_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sender_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    receiver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint(
            "sender_id <> receiver_id",
            name="ck_contact_requests_different_users",
        ),
        Index(
            "uq_contact_requests_pair",
            func.least(sender_id, receiver_id),
            func.greatest(sender_id, receiver_id),
            unique=True,
        ),
    )

    status: Mapped[ContactStatusEnum] = mapped_column(
        SAEnum(
            ContactStatusEnum,
            name="contactstatusenum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ContactStatusEnum.BLANK,
        server_default="blank",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    sender: Mapped["User"] = relationship(
        "User", foreign_keys=[sender_id], back_populates="sent_requests"
    )
    receiver: Mapped["User"] = relationship(
        "User", foreign_keys=[receiver_id], back_populates="received_requests"
    )


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    owner: Mapped["User"] = relationship(
        "User", foreign_keys=[owner_id], back_populates="created_chats"
    )
    participant_links: Mapped[list["ChatParticipant"]] = relationship(
        "ChatParticipant",
        back_populates="chat",
        cascade="all, delete-orphan",
    )
    events: Mapped[list["ChatEvent"]] = relationship(
        "ChatEvent",
        back_populates="chat",
        cascade="all, delete-orphan",
        order_by="ChatEvent.timestamp",
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan",
    )

    @property
    def participants(self) -> list["User"]:
        return [membership.user for membership in self.participant_links]


class ChatParticipant(Base):
    __tablename__ = "chat_participants"

    chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    invited_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    chat: Mapped["Chat"] = relationship("Chat", back_populates="participant_links")
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="chat_memberships",
    )


class ChatEvent(Base):
    __tablename__ = "chat_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    target_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[ChatEventTypeEnum] = mapped_column(
        SAEnum(
            ChatEventTypeEnum,
            name="chateventtypeenum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (Index("ix_chat_events_chat_timestamp", "chat_id", "timestamp"),)

    chat: Mapped["Chat"] = relationship("Chat", back_populates="events")
    actor: Mapped["User"] = relationship(
        "User", foreign_keys=[actor_id], back_populates="performed_chat_events"
    )
    target_user: Mapped["User | None"] = relationship(
        "User", foreign_keys=[target_user_id], back_populates="targeted_chat_events"
    )


class Message(Base):
    __tablename__ = "messages"

    __table_args__ = (
        Index("ix_messages_recipient_delivered", "recipient_id", "is_delivered"),
        Index("ix_messages_chat_timestamp", "chat_id", "timestamp"),
        CheckConstraint(
            "(content IS NOT NULL) <> (file_content IS NOT NULL)",
            name="ck_messages_single_payload",
        ),
        CheckConstraint(
            "file_size IS NULL OR file_size >= 0",
            name="ck_messages_nonnegative_file_size",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sender_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    recipient_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    chat_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE")
    )
    reply_to_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )

    content_type: Mapped[MessageContentTypeEnum] = mapped_column(
        SAEnum(
            MessageContentTypeEnum,
            name="messagecontenttypeenum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=MessageContentTypeEnum.TEXT,
        server_default=MessageContentTypeEnum.TEXT.value,
    )
    content: Mapped[str | None] = mapped_column(Text)

    file_name: Mapped[str | None] = mapped_column(String(255))
    file_content: Mapped[bytes | None] = mapped_column(LargeBinary)
    file_size: Mapped[int | None]
    file_mime_type: Mapped[MessageContentMimeTypeEnum] = mapped_column(
        SAEnum(
            MessageContentMimeTypeEnum,
            name="messagecontentmimetypeenum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=MessageContentMimeTypeEnum.TEXT,
        server_default=MessageContentMimeTypeEnum.TEXT.value,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    is_delivered: Mapped[bool] = mapped_column(default=False)

    ephemeral_public_key: Mapped[str] = mapped_column(Text)
    ephemeral_signature: Mapped[str] = mapped_column(Text)

    sender: Mapped["User"] = relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="sent_messages",
    )
    recipient: Mapped["User"] = relationship(
        "User",
        foreign_keys=[recipient_id],
        back_populates="received_messages",
    )
    chat: Mapped["Chat | None"] = relationship(
        "Chat",
        back_populates="messages",
    )
    reply_to: Mapped["Message | None"] = relationship(
        "Message",
        remote_side=[id],
        back_populates="replies",
    )
    replies: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="reply_to",
    )


class FileTransfer(Base):
    __tablename__ = "file_transfers"

    __table_args__ = (
        CheckConstraint(
            "total_size >= 0",
            name="ck_file_transfers_nonnegative_size",
        ),
        CheckConstraint(
            "chunk_size > 0",
            name="ck_file_transfers_positive_chunk_size",
        ),
        CheckConstraint(
            '"offset" >= 0 AND "offset" <= total_size',
            name="ck_file_transfers_valid_offset",
        ),
        Index(
            "ix_file_transfers_recipient_status_completed",
            "recipient_id",
            "status",
            "completed_at",
        ),
    )

    file_id: Mapped[UUID] = mapped_column(primary_key=True)
    upload_id: Mapped[UUID] = mapped_column(unique=True, index=True)
    message_id: Mapped[UUID] = mapped_column(unique=True, index=True)
    sender_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    chat_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
    )
    total_size: Mapped[int]
    chunk_size: Mapped[int]
    offset: Mapped[int] = mapped_column(default=0, server_default="0")
    encrypted_metadata: Mapped[str] = mapped_column(Text)
    ephemeral_public_key: Mapped[str] = mapped_column(Text)
    ephemeral_signature: Mapped[str] = mapped_column(Text)
    status: Mapped[FileTransferStatusEnum] = mapped_column(
        SAEnum(
            FileTransferStatusEnum,
            name="filetransferstatusenum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=FileTransferStatusEnum.UPLOADING,
        server_default=FileTransferStatusEnum.UPLOADING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FileChunk(Base):
    __tablename__ = "file_chunks"

    __table_args__ = (
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_file_chunks_nonnegative_index",
        ),
    )

    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("file_transfers.file_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_index: Mapped[int] = mapped_column(primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
