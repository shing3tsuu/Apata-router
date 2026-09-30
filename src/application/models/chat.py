from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ChatNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Chat name cannot be blank")
        return normalized_value


class CreateChatRequest(ChatNameRequest):
    pass


class UpdateChatRequest(ChatNameRequest):
    pass


class AddChatParticipantRequest(BaseModel):
    user_id: UUID


class ChatResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    created_at: datetime


class ChatParticipantResponse(BaseModel):
    chat_id: UUID
    user_id: UUID
    invited_by_user_id: UUID | None
    joined_at: datetime
    left_at: datetime | None = None


class ChatEventResponse(BaseModel):
    id: UUID
    chat_id: UUID
    # ``user_id`` is the legacy client field name for the event actor.
    user_id: UUID
    event_type: str
    timestamp: datetime
    target_user_id: UUID | None


class ChatParticipantChangeResponse(BaseModel):
    participant: ChatParticipantResponse
    event: ChatEventResponse
