import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserCreateDTO(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_]+$")

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, value: str) -> str:
        if not re.match("^[a-zA-Z0-9_]*$", value):
            raise ValueError(
                "Username must be alphanumeric and can contain underscores"
            )
        return value


class PublicKeyUpdateDTO(BaseModel):
    ed_public_key: str | None = None
    ecdh_public_key: str | None = None
    ecdh_signature: str | None = None

    @field_validator("ed_public_key", "ecdh_public_key")
    @classmethod
    def validate_public_key_format(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("-----BEGIN") or "KEY-----" not in value
        ):
            raise ValueError("Invalid public key format. Expected PEM format.")
        return value


class UserRegisterRequest(UserCreateDTO):
    ed_public_key: str
    ecdh_public_key: str
    ecdh_signature: str | None = None

    @field_validator("ed_public_key", "ecdh_public_key")
    @classmethod
    def validate_public_key_format(cls, value: str) -> str:
        if not value.startswith("-----BEGIN") or "KEY-----" not in value:
            raise ValueError("Invalid public key format. Expected PEM format.")
        return value


class UserRegisterResponse(BaseModel):
    id: UUID
    username: str


class PublicKeyResponse(BaseModel):
    user_id: UUID
    ed_public_key: str
    ecdh_public_key: str
    ecdh_signature: str | None


class ECDHPublicKeyBatchRequest(BaseModel):
    user_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_user_ids(self) -> "ECDHPublicKeyBatchRequest":
        if len(self.user_ids) != len(set(self.user_ids)):
            raise ValueError("ECDH key user IDs must be unique")
        return self


class ECDHPublicKeyResponse(BaseModel):
    user_id: UUID
    ecdh_public_key: str
    ecdh_signature: str


class ChallengeLoginRequest(BaseModel):
    username: str
    signature: str  # Base64-encoded signature


class ChallengeRequest(BaseModel):
    username: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: UUID
    username: str
    ed_public_key: str | None = None
    ecdh_public_key: str | None = None
    ecdh_signature: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LogoutResponse(BaseModel):
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    service: str
    redis: str
