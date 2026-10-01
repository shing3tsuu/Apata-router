from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .structures import (
    ChatEventTypeEnum,
    ContactStatusEnum,
    FileTransferStatusEnum,
    MessageContentMimeTypeEnum,
    MessageContentTypeEnum,
)


class CreateUserDTO(BaseModel):
    username: str
    ed_public_key: str
    ecdh_public_key: str
    ecdh_signature: str | None
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    online: bool = False


class UpdateUserDTO(BaseModel):
    username: str | None = None
    ed_public_key: str | None = None
    ecdh_public_key: str | None = None
    ecdh_signature: str | None = None
    last_seen: datetime | None = None
    online: bool | None = None


class UserDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    ed_public_key: str | None
    ecdh_public_key: str | None
    ecdh_signature: str | None
    last_seen: datetime
    online: bool


class UserWithStatusDTO(UserDTO):
    status: ContactStatusEnum


class ContactParticipantsDTO(BaseModel):
    sender_id: UUID
    receiver_id: UUID

    @model_validator(mode="after")
    def validate_distinct_participants(self) -> "ContactParticipantsDTO":
        if self.sender_id == self.receiver_id:
            raise ValueError("A user cannot create a contact request to themselves")
        return self


class CreateContactDTO(ContactParticipantsDTO):
    status: ContactStatusEnum = ContactStatusEnum.BLANK
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UpdateContactDTO(ContactParticipantsDTO):
    status: ContactStatusEnum


class ContactDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_id: UUID
    receiver_id: UUID
    status: ContactStatusEnum
    created_at: datetime


class ChatNameDTO(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Chat name cannot be blank")
        return normalized_value


class CreateChatDTO(ChatNameDTO):
    owner_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UpdateChatDTO(ChatNameDTO):
    pass


class ChatDTO(CreateChatDTO):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class CreateChatParticipantDTO(BaseModel):
    chat_id: UUID
    user_id: UUID
    invited_by_user_id: UUID | None = None
    joined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    left_at: datetime | None = None


class ChatParticipantDTO(CreateChatParticipantDTO):
    model_config = ConfigDict(from_attributes=True)


class CreateChatEventDTO(BaseModel):
    chat_id: UUID
    actor_id: UUID
    target_user_id: UUID | None = None
    event_type: ChatEventTypeEnum
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatEventDTO(CreateChatEventDTO):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class ChatParticipantChangeDTO(BaseModel):
    """Result of a membership mutation and its immutable timeline event."""

    participant: ChatParticipantDTO
    event: ChatEventDTO


class CreateMessageDTO(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    sender_id: UUID
    recipient_id: UUID
    chat_id: UUID | None = None
    reply_to_id: UUID | None = None
    content_type: MessageContentTypeEnum = MessageContentTypeEnum.TEXT
    content: str | None = Field(default=None, min_length=1)
    file_name: str | None = Field(default=None, min_length=1, max_length=255)
    file_content: bytes | None = None
    # File size describes the user-visible original file, not ciphertext length.
    file_size: int | None = Field(default=None, ge=0)
    file_mime_type: MessageContentMimeTypeEnum = MessageContentMimeTypeEnum.TEXT
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_delivered: bool = False
    failed: bool | None = None
    ephemeral_public_key: str = Field(min_length=1)
    ephemeral_signature: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_payload(self) -> "CreateMessageDTO":
        has_content = self.content is not None
        has_file = self.file_content is not None
        if has_content == has_file:
            raise ValueError("A message must contain exactly one payload type")

        if has_file and (self.file_name is None or self.file_size is None):
            raise ValueError("File messages require name and size metadata")

        if has_content and (self.file_name is not None or self.file_size is not None):
            raise ValueError("Text messages cannot contain file metadata")

        return self


class CreateMessageTextDTO(CreateMessageDTO):
    content_type: MessageContentTypeEnum = MessageContentTypeEnum.TEXT
    content: str = Field(min_length=1)
    file_name: None = None
    file_content: None = None
    file_size: None = None
    file_mime_type: MessageContentMimeTypeEnum = MessageContentMimeTypeEnum.TEXT

    @field_validator("content_type")
    @classmethod
    def validate_text_content_type(
        cls, value: MessageContentTypeEnum
    ) -> MessageContentTypeEnum:
        if value not in {MessageContentTypeEnum.TEXT, MessageContentTypeEnum.CODE}:
            raise ValueError("Text messages must have text or code content type")
        return value


class CreateMessageFileDTO(CreateMessageDTO):
    content: None = None
    file_name: str = Field(min_length=1, max_length=255)
    file_content: bytes
    file_size: int = Field(ge=0)
    file_mime_type: MessageContentMimeTypeEnum

    @field_validator("content_type")
    @classmethod
    def validate_file_content_type(
        cls, value: MessageContentTypeEnum
    ) -> MessageContentTypeEnum:
        if value in {MessageContentTypeEnum.TEXT, MessageContentTypeEnum.CODE}:
            raise ValueError("File messages cannot have text or code content type")
        return value


class MessageDTO(CreateMessageDTO):
    model_config = ConfigDict(from_attributes=True)


class MessageProcessingResultDTO(BaseModel):
    message_id: UUID
    failed: bool


class CreateFileTransferDTO(BaseModel):
    file_id: UUID
    upload_id: UUID = Field(default_factory=uuid4)
    message_id: UUID
    sender_id: UUID
    recipient_id: UUID
    chat_id: UUID | None = None
    total_size: int = Field(ge=0)
    chunk_size: int = Field(gt=0)
    offset: int = Field(default=0, ge=0)
    encrypted_metadata: str = Field(min_length=1)
    ephemeral_public_key: str = Field(min_length=1)
    ephemeral_signature: str = Field(min_length=1)
    status: FileTransferStatusEnum = FileTransferStatusEnum.UPLOADING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_offset(self) -> "CreateFileTransferDTO":
        if self.offset > self.total_size:
            raise ValueError("File transfer offset cannot exceed total size")
        return self


class FileTransferDTO(CreateFileTransferDTO):
    model_config = ConfigDict(from_attributes=True)
