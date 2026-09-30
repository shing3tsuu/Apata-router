from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateFileUploadRequest(BaseModel):
    file_id: UUID
    recipient_id: UUID
    message_id: UUID
    chat_id: UUID | None = None
    total_size: int = Field(ge=0)
    chunk_size: int = Field(gt=0)
    encrypted_metadata: str = Field(min_length=1)
    ephemeral_public_key: str = Field(min_length=1)
    ephemeral_signature: str = Field(min_length=1)

    @field_validator("file_id")
    @classmethod
    def validate_file_id(cls, value: UUID) -> UUID:
        if value.version != 7:
            raise ValueError("file_id must be UUIDv7")
        return value


class FileUploadSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    upload_id: UUID
    file_id: UUID
    chunk_size: int
    offset: int
    expires_at: datetime | None


class CompleteFileUploadResponse(BaseModel):
    file_id: UUID


class UndeliveredFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    file_id: UUID
    message_id: UUID
    sender_id: UUID
    chat_id: UUID | None
    encrypted_metadata: str
    ephemeral_public_key: str
    ephemeral_signature: str
    timestamp: datetime = Field(validation_alias="completed_at")


class UndeliveredFilesResponse(BaseModel):
    has_files: bool
    files: list[UndeliveredFileResponse]


class AcknowledgeFilesRequest(BaseModel):
    file_ids: list[UUID] = Field(min_length=1, max_length=1000)


class AcknowledgeFilesResponse(BaseModel):
    acknowledged: int
