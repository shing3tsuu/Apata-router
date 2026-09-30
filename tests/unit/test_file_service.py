from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4, uuid7

import pytest

from src.adapters.database.dao.chat import ChatDAO
from src.adapters.database.dao.common import CommonDAO
from src.adapters.database.dao.file import FileDAO
from src.adapters.database.dao.user import UserDAO
from src.adapters.database.dto import FileTransferDTO
from src.adapters.database.service.file import FileService
from src.adapters.database.structures import FileTransferStatusEnum
from src.errors.error import (
    FileTransferOffsetConflictError,
    FileTransferValidationError,
)


def _transfer(
    *,
    file_id: UUID | None = None,
    upload_id: UUID | None = None,
    sender_id: UUID | None = None,
    offset: int = 0,
    total_size: int = 10,
    chunk_size: int = 10,
) -> FileTransferDTO:
    return FileTransferDTO(
        file_id=file_id or uuid7(),
        upload_id=upload_id or uuid4(),
        message_id=uuid7(),
        sender_id=sender_id or uuid4(),
        recipient_id=uuid4(),
        total_size=total_size,
        chunk_size=chunk_size,
        offset=offset,
        encrypted_metadata="encrypted-metadata",
        ephemeral_public_key="ephemeral-key",
        ephemeral_signature="ephemeral-signature",
        status=FileTransferStatusEnum.UPLOADING,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _service() -> tuple[FileService, AsyncMock, AsyncMock]:
    file_dao = AsyncMock(spec=FileDAO)
    chat_dao = AsyncMock(spec=ChatDAO)
    user_dao = AsyncMock(spec=UserDAO)
    common_dao = AsyncMock(spec=CommonDAO)
    return (
        FileService(
            file_dao=file_dao,
            chat_dao=chat_dao,
            user_dao=user_dao,
            common_dao=common_dao,
        ),
        file_dao,
        common_dao,
    )


async def test_append_chunk_persists_once_and_advances_offset() -> None:
    sender_id = uuid4()
    transfer = _transfer(sender_id=sender_id, total_size=3, chunk_size=3)
    service, file_dao, common_dao = _service()
    file_dao.get_transfer_by_upload_id.return_value = transfer
    file_dao.append_chunk.return_value = 3

    offset = await service.append_chunk(
        upload_id=transfer.upload_id,
        sender_id=sender_id,
        offset=0,
        ciphertext=b"abc",
    )

    assert offset == 3
    file_dao.append_chunk.assert_awaited_once_with(
        upload_id=transfer.upload_id,
        expected_offset=0,
        chunk_index=0,
        ciphertext=b"abc",
    )
    common_dao.commit.assert_awaited_once()


async def test_append_chunk_rejects_stale_offset_before_database_write() -> None:
    sender_id = uuid4()
    transfer = _transfer(sender_id=sender_id, offset=3, total_size=6, chunk_size=3)
    service, file_dao, common_dao = _service()
    file_dao.get_transfer_by_upload_id.return_value = transfer

    with pytest.raises(FileTransferOffsetConflictError, match="does not match"):
        await service.append_chunk(
            upload_id=transfer.upload_id,
            sender_id=sender_id,
            offset=0,
            ciphertext=b"abc",
        )

    file_dao.append_chunk.assert_not_awaited()
    common_dao.commit.assert_not_awaited()


async def test_create_upload_rejects_non_uuidv7_file_id() -> None:
    service, _, common_dao = _service()
    transfer = _transfer(file_id=uuid4())

    with pytest.raises(FileTransferValidationError, match="UUIDv7"):
        await service.create_upload(transfer)

    common_dao.commit.assert_not_awaited()
