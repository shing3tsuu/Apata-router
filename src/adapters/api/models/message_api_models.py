from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import json

class MessageSendRequest(BaseModel):
    recipient_id: int
    message: str
    content_type: str
    ephemeral_public_key: str

class MessageResponse(BaseModel):
    id: int
    sender_id: int
    recipient_id: int
    message: str
    content_type: str | None = None
    timestamp: str
    is_delivered: bool
    ephemeral_public_key: str

class UndeliveredMessageResponse(BaseModel):
    has_messages: bool
    messages: list[MessageResponse] | None = []

class PollingResponse(BaseModel):
    has_messages: bool
    messages: list[MessageResponse] | None = []

class AckRequest(BaseModel):
    message_ids: list[int]