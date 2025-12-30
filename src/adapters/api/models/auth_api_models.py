from pydantic import BaseModel, Field, validator
from typing import Optional
import re

class UserCreateDTO(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_]+$")

    @validator('username')
    def username_alphanumeric(cls, v):
        if not re.match("^[a-zA-Z0-9_]*$", v):
            raise ValueError('Username must be alphanumeric and can contain underscores')
        return v

class PublicKeyUpdateDTO(BaseModel):
    ecdsa_public_key: str | None = None
    ecdh_public_key: str | None = None
    ecdh_signature: str | None = None

    @validator('ecdsa_public_key', 'ecdh_public_key')
    def validate_public_key_format(cls, v):
        if v is not None:
            if not v.startswith('-----BEGIN') or 'KEY-----' not in v:
                raise ValueError('Invalid public key format. Expected PEM format.')
        return v

class UserRegisterRequest(UserCreateDTO):
    ecdsa_public_key: str
    ecdh_public_key: str
    ecdh_signature: str | None = None

    @validator('ecdsa_public_key')
    def validate_ecdsa_key(cls, v):
        if not v.startswith('-----BEGIN') or 'KEY-----' not in v:
            raise ValueError('Invalid ECDSA public key format. Expected PEM format.')
        return v

    @validator('ecdh_public_key')
    def validate_ecdh_key(cls, v):
        if v is not None and (not v.startswith('-----BEGIN') or 'KEY-----' not in v):
            raise ValueError('Invalid ECDH public key format. Expected PEM format.')
        return v

class UserRegisterResponse(BaseModel):
    id: int
    username: str

class PublicKeyResponse(BaseModel):
    user_id: int
    ecdsa_public_key: str
    ecdh_public_key: str
    ecdh_signature: str | None

class ChallengeLoginRequest(BaseModel):
    username: str
    signature: str  # Base64-encoded signature

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class UserResponse(BaseModel):
    id: int
    username: str
    ecdsa_public_key: str | None = None
    ecdh_public_key: str | None = None
    ecdh_signature: str | None = None

    class Config:
        from_attributes = True

class LogoutResponse(BaseModel):
    status: str
    message: str

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    service: str
    redis: str