from pydantic import BaseModel, constr, Field, validator
from datetime import datetime


class UserContactResponse(BaseModel):
    id: int
    username: str
    ecdh_public_key: str
    last_seen: datetime
    status: str | None = None
    online: bool | None = None

class SentContactRequest(BaseModel):
    receiver_id: int

class ContactRequestResponse(BaseModel):
    sender_id: int
    receiver_id: int
    status: str
    created_at: datetime

class GetUserContactsRequests(BaseModel):
    receiver_id: int
    status: str