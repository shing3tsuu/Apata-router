from pydantic import BaseModel, constr, validator
from datetime import datetime
from typing import List

class UserRequestDTO(BaseModel):
    username: str | None = None
    ecdsa_public_key: str | None = None
    ecdh_public_key: str | None = None
    last_seen: datetime | None = None
    online: bool | None = None

class UserDTO(UserRequestDTO):
    id: int

class UserWithStatusDTO(BaseModel):
    id: int
    username: str | None = None
    ecdsa_public_key: str | None = None
    ecdh_public_key: str | None = None
    last_seen: datetime | None = None
    status: str | None = None # status: 'accepted', 'pending', 'rejected', 'none'
    online: bool | None = None


class ContactRequestDTO(BaseModel):
    sender_id: int | None = None
    receiver_id: int | None = None
    status: str | None = None # status: 'accepted', 'pending', 'rejected', 'none'
    created_at: datetime | None = None

class ContactDTO(ContactRequestDTO):
    id: int

class MessageRequestDTO(BaseModel):
    sender_id: int
    recipient_id: int
    message: str
    content_type: str | None = None
    timestamp: datetime
    is_delivered: bool
    ephemeral_public_key: str

class MessageDTO(MessageRequestDTO):
    id: int