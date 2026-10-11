from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.adapters.database.structures import MessageContentTypeEnum

MAX_CHAT_RECIPIENTS = 100
MAX_ENCRYPTED_CHAT_DELIVERY_LENGTH = 64 * 1024
MAX_ENCRYPTED_CHAT_BATCH_LENGTH = 1024 * 1024


class SendTextMessageRequest(BaseModel):
    recipient_id: UUID
    chat_id: UUID | None = None
    reply_to_id: UUID | None = None
    message: str = Field(min_length=1)
    message_id: UUID
    content_type: Literal[MessageContentTypeEnum.TEXT, MessageContentTypeEnum.CODE] = (
        MessageContentTypeEnum.TEXT
    )
    ephemeral_public_key: str = Field(min_length=1)
    ephemeral_signature: str = Field(min_length=1)


class ChatMessageDeliveryRequest(BaseModel):
    recipient_id: UUID
    message_id: UUID
    reply_to_id: UUID | None = None
    message: str = Field(
        min_length=1,
        max_length=MAX_ENCRYPTED_CHAT_DELIVERY_LENGTH,
    )


class SendChatTextMessageRequest(BaseModel):
    general_message_uuid: UUID
    reply_to_general_message_uuid: UUID | None = None
    content_type: Literal[MessageContentTypeEnum.TEXT] = MessageContentTypeEnum.TEXT
    ephemeral_public_key: str = Field(min_length=1)
    ephemeral_signature: str = Field(min_length=1)
    deliveries: list[ChatMessageDeliveryRequest] = Field(
        min_length=1,
        max_length=MAX_CHAT_RECIPIENTS,
    )

    @model_validator(mode="after")
    def validate_unique_deliveries(self) -> "SendChatTextMessageRequest":
        if self.reply_to_general_message_uuid is None and any(
            delivery.reply_to_id is not None for delivery in self.deliveries
        ):
            raise ValueError(
                "Chat reply deliveries require reply_to_general_message_uuid"
            )
        recipient_ids = [delivery.recipient_id for delivery in self.deliveries]
        if len(recipient_ids) != len(set(recipient_ids)):
            raise ValueError("Chat message recipient IDs must be unique")

        message_ids = [delivery.message_id for delivery in self.deliveries]
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("Chat message delivery IDs must be unique")

        encrypted_payload_length = sum(
            len(delivery.message.encode("utf-8")) for delivery in self.deliveries
        )
        if encrypted_payload_length > MAX_ENCRYPTED_CHAT_BATCH_LENGTH:
            raise ValueError("Encrypted chat message batch is too large")
        return self


class ChatReplyTargetResponse(BaseModel):
    user_id: UUID
    message_id: UUID


class MessageProcessingResult(BaseModel):
    message_id: UUID
    failed: bool


class AcknowledgeMessagesRequest(BaseModel):
    results: list[MessageProcessingResult] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_unique_message_ids(self) -> "AcknowledgeMessagesRequest":
        message_ids = [result.message_id for result in self.results]
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("Acknowledgement message IDs must be unique")
        return self


class MessageTextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    general_message_uuid: UUID | None
    sender_id: UUID
    recipient_id: UUID
    chat_id: UUID | None
    reply_to_id: UUID | None
    reply_to_general_message_uuid: UUID | None
    content_type: MessageContentTypeEnum
    message: str = Field(validation_alias="content")
    timestamp: datetime
    is_delivered: bool
    failed: bool | None
    ephemeral_public_key: str
    ephemeral_signature: str


class UndeliveredMessagesResponse(BaseModel):
    has_messages: bool
    messages: list[MessageTextResponse]


class AcknowledgeMessagesResponse(BaseModel):
    acknowledged: int


class FailedMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    recipient_id: UUID
    chat_id: UUID | None
    timestamp: datetime
    is_delivered: bool
    failed: Literal[True]


class FailedMessagesResponse(BaseModel):
    has_messages: bool
    messages: list[FailedMessageResponse]
