from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.adapters.database.dao.chat import ChatDAO
from src.adapters.database.dao.common import CommonDAO, error_handler
from src.adapters.database.dao.file import FileDAO
from src.adapters.database.dao.user import UserDAO
from src.adapters.database.dto import CreateFileTransferDTO, FileTransferDTO
from src.adapters.database.structures import FileTransferStatusEnum
from src.errors.error import (
    ChatNotFoundError,
    ChatParticipantNotFoundError,
    FileTransferAccessDeniedError,
    FileTransferExpiredError,
    FileTransferIncompleteError,
    FileTransferNotFoundError,
    FileTransferNotReadyError,
    FileTransferOffsetConflictError,
    FileTransferValidationError,
    UserNotFoundError,
)


class FileService:
    _MAX_CIPHERTEXT_FILE_SIZE = 1024 * 1024 * 1024
    _MAX_CIPHERTEXT_CHUNK_SIZE = 8 * 1024 * 1024
    _UPLOAD_TTL = timedelta(hours=24)

    def __init__(
        self,
        file_dao: FileDAO,
        chat_dao: ChatDAO,
        user_dao: UserDAO,
        common_dao: CommonDAO,
    ):
        self._file_dao = file_dao
        self._chat_dao = chat_dao
        self._user_dao = user_dao
        self._common_dao = common_dao

    @error_handler
    async def create_upload(self, transfer: CreateFileTransferDTO) -> FileTransferDTO:
        if transfer.file_id.version != 7:
            raise FileTransferValidationError("File ID must be UUIDv7")
        if transfer.total_size > self._MAX_CIPHERTEXT_FILE_SIZE:
            raise FileTransferValidationError("Encrypted file exceeds the size limit")
        if transfer.chunk_size > self._MAX_CIPHERTEXT_CHUNK_SIZE:
            raise FileTransferValidationError("Encrypted chunk exceeds the size limit")

        recipient = await self._user_dao.get_user_by_id(transfer.recipient_id)
        if recipient is None:
            raise UserNotFoundError(
                "Recipient user not found",
                context={"user_id": str(transfer.recipient_id)},
            )

        if transfer.chat_id is not None:
            chat = await self._chat_dao.get_chat_by_id(transfer.chat_id)
            if chat is None:
                raise ChatNotFoundError(
                    "Chat not found", context={"chat_id": str(transfer.chat_id)}
                )

            participants = await self._chat_dao.get_participants(transfer.chat_id)
            participant_ids = {participant.user_id for participant in participants}
            required_participant_ids = {transfer.sender_id, transfer.recipient_id}
            if required_participant_ids - participant_ids:
                raise ChatParticipantNotFoundError(
                    "Every file sender and recipient must be a chat participant",
                    context={
                        "chat_id": str(transfer.chat_id),
                        "user_ids": sorted(
                            str(user_id)
                            for user_id in required_participant_ids - participant_ids
                        ),
                    },
                )

        prepared_transfer = transfer.model_copy(
            update={"expires_at": datetime.now(UTC) + self._UPLOAD_TTL}
        )
        return await self._file_dao.create_transfer(prepared_transfer)

    async def get_upload_session(
        self, upload_id: UUID, sender_id: UUID
    ) -> FileTransferDTO:
        transfer = await self._file_dao.get_transfer_by_upload_id(upload_id)
        if transfer is None:
            raise FileTransferNotFoundError(
                "Upload not found", context={"upload_id": str(upload_id)}
            )
        if transfer.sender_id != sender_id:
            raise FileTransferAccessDeniedError("Upload access is forbidden")
        if transfer.status is not FileTransferStatusEnum.UPLOADING:
            raise FileTransferNotReadyError("Upload is no longer resumable")
        if transfer.expires_at is not None and transfer.expires_at <= datetime.now(UTC):
            raise FileTransferExpiredError("Upload session has expired")
        return transfer

    @error_handler
    async def append_chunk(
        self,
        *,
        upload_id: UUID,
        sender_id: UUID,
        offset: int,
        ciphertext: bytes,
    ) -> int:
        transfer = await self.get_upload_session(upload_id, sender_id)
        if transfer.offset != offset:
            raise FileTransferOffsetConflictError(
                "Upload offset does not match the server state",
                context={"offset": transfer.offset},
            )
        if not ciphertext:
            raise FileTransferValidationError("Encrypted chunk cannot be empty")

        expected_chunk_size = min(
            transfer.chunk_size, transfer.total_size - transfer.offset
        )
        if len(ciphertext) != expected_chunk_size:
            raise FileTransferValidationError(
                "Encrypted chunk size does not match the upload state",
                context={"expected_size": expected_chunk_size},
            )

        updated_offset = await self._file_dao.append_chunk(
            upload_id=upload_id,
            expected_offset=offset,
            chunk_index=offset // transfer.chunk_size,
            ciphertext=ciphertext,
        )
        if updated_offset is not None:
            return updated_offset

        current_transfer = await self._file_dao.get_transfer_by_upload_id(upload_id)
        if current_transfer is None:
            raise FileTransferNotFoundError(
                "Upload not found", context={"upload_id": str(upload_id)}
            )
        raise FileTransferOffsetConflictError(
            "Upload offset does not match the server state",
            context={"offset": current_transfer.offset},
        )

    @error_handler
    async def complete_upload(
        self, upload_id: UUID, sender_id: UUID
    ) -> FileTransferDTO:
        transfer = await self.get_upload_session(upload_id, sender_id)
        if transfer.offset != transfer.total_size:
            raise FileTransferIncompleteError(
                "Upload is incomplete",
                context={"offset": transfer.offset, "total_size": transfer.total_size},
            )

        completed_transfer = await self._file_dao.complete_transfer(upload_id)
        if completed_transfer is not None:
            return completed_transfer

        raise FileTransferNotReadyError("Upload could not be completed")

    @error_handler
    async def abort_upload(self, upload_id: UUID, sender_id: UUID) -> bool:
        transfer = await self._file_dao.get_transfer_by_upload_id(upload_id)
        if transfer is None:
            raise FileTransferNotFoundError(
                "Upload not found", context={"upload_id": str(upload_id)}
            )
        if transfer.sender_id != sender_id:
            raise FileTransferAccessDeniedError("Upload access is forbidden")
        if transfer.status is not FileTransferStatusEnum.UPLOADING:
            return False
        return await self._file_dao.abort_transfer(upload_id)

    async def get_undelivered_files(self, recipient_id: UUID) -> list[FileTransferDTO]:
        return await self._file_dao.get_undelivered_transfers(recipient_id)

    async def get_chunk(
        self, file_id: UUID, recipient_id: UUID, chunk_index: int
    ) -> bytes:
        transfer = await self._file_dao.get_transfer_by_file_id(file_id)
        if transfer is None:
            raise FileTransferNotFoundError(
                "File not found", context={"file_id": str(file_id)}
            )
        if transfer.recipient_id != recipient_id:
            raise FileTransferAccessDeniedError("File access is forbidden")
        if transfer.status not in {
            FileTransferStatusEnum.COMPLETED,
            FileTransferStatusEnum.DELIVERED,
        }:
            raise FileTransferNotReadyError("File upload is not complete")

        ciphertext = await self._file_dao.get_chunk(file_id, chunk_index)
        if ciphertext is None:
            raise FileTransferNotFoundError(
                "File chunk not found",
                context={"file_id": str(file_id), "chunk_index": chunk_index},
            )
        return ciphertext

    @error_handler
    async def acknowledge_files(
        self, recipient_id: UUID, file_ids: Sequence[UUID]
    ) -> int:
        acknowledged_file_ids = await self._file_dao.acknowledge_transfers(
            recipient_id, file_ids
        )
        return len(acknowledged_file_ids)
