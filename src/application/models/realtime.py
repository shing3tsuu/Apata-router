from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

RealtimeEventType = Literal[
    "session_ready",
    "message_available",
    "presence_changed",
    "contact_changed",
    "chat_changed",
]


class RealtimeEvent(BaseModel):
    version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid4)
    type: RealtimeEventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)


class RealtimeBrokerEvent(RealtimeEvent):
    recipient_ids: list[UUID] = Field(min_length=1)

    def public_event(self) -> RealtimeEvent:
        return RealtimeEvent(
            version=self.version,
            event_id=self.event_id,
            type=self.type,
            occurred_at=self.occurred_at,
            payload=self.payload,
        )
