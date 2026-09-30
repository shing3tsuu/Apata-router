from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


class AcknowledgeMessagesRequest(BaseModel):
    message_ids: list[UUID] = Field(min_length=1, max_length=1000)


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
    ephemeral_public_key: str
    ephemeral_signature: str


class UndeliveredMessagesResponse(BaseModel):
    has_messages: bool
    messages: list[MessageTextResponse]


class AcknowledgeMessagesResponse(BaseModel):
    acknowledged: int
