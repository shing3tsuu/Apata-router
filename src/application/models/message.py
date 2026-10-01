from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.adapters.database.structures import MessageContentTypeEnum


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
    sender_id: UUID
    recipient_id: UUID
    chat_id: UUID | None
    reply_to_id: UUID | None
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
