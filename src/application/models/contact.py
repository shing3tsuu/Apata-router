from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateContactRequest(BaseModel):
    receiver_id: UUID


class AnswerContactRequest(BaseModel):
    action: Literal["accept", "reject"]


class ContactPublicResponse(BaseModel):
    """A contact as seen by the authenticated user."""

    contact_id: UUID | None
    user_id: UUID
    username: str
    ed_public_key: str
    ecdh_public_key: str
    status: str
    online: bool | None
    last_seen: datetime | None


class ContactPageResponse(BaseModel):
    items: list[ContactPublicResponse]
    next_after_id: UUID | None = Field(default=None)
