from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.dto import CreateFileTransferDTO, FileTransferDTO
from src.adapters.database.structures import (
    FileChunk,
    FileTransfer,
    FileTransferStatusEnum,
)


class FileDAO:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_transfer(self, transfer: CreateFileTransferDTO) -> FileTransferDTO:
        stmt = (
            insert(FileTransfer).values(**transfer.model_dump()).returning(FileTransfer)
        )
        result = await self._session.scalar(stmt)
        assert result is not None
        return FileTransferDTO.model_validate(result, from_attributes=True)

    async def get_transfer_by_upload_id(
        self, upload_id: UUID
    ) -> FileTransferDTO | None:
        result = await self._session.scalar(
            select(FileTransfer).where(FileTransfer.upload_id == upload_id)
        )
        if result is None:
            return None
        return FileTransferDTO.model_validate(result, from_attributes=True)

    async def get_transfer_by_file_id(self, file_id: UUID) -> FileTransferDTO | None:
        result = await self._session.scalar(
            select(FileTransfer).where(FileTransfer.file_id == file_id)
        )
        if result is None:
            return None
        return FileTransferDTO.model_validate(result, from_attributes=True)

    async def append_chunk(
        self,
        *,
        upload_id: UUID,
        expected_offset: int,
        chunk_index: int,
        ciphertext: bytes,
    ) -> int | None:
        next_offset = expected_offset + len(ciphertext)
        offset_stmt = (
            update(FileTransfer)
            .where(
                FileTransfer.upload_id == upload_id,
                FileTransfer.status == FileTransferStatusEnum.UPLOADING,
                FileTransfer.offset == expected_offset,
            )
            .values(offset=next_offset)
            .returning(FileTransfer.offset)
        )
        updated_offset = await self._session.scalar(offset_stmt)
        if updated_offset is None:
            return None

        await self._session.execute(
            insert(FileChunk).values(
                file_id=(
                    select(FileTransfer.file_id)
                    .where(FileTransfer.upload_id == upload_id)
                    .scalar_subquery()
                ),
                chunk_index=chunk_index,
                ciphertext=ciphertext,
            )
        )
        return updated_offset

    async def complete_transfer(self, upload_id: UUID) -> FileTransferDTO | None:
        stmt = (
            update(FileTransfer)
            .where(
                FileTransfer.upload_id == upload_id,
                FileTransfer.status == FileTransferStatusEnum.UPLOADING,
                FileTransfer.offset == FileTransfer.total_size,
            )
            .values(
                status=FileTransferStatusEnum.COMPLETED,
                completed_at=datetime.now(UTC),
                expires_at=None,
            )
            .returning(FileTransfer)
        )
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return FileTransferDTO.model_validate(result, from_attributes=True)

    async def abort_transfer(self, upload_id: UUID) -> bool:
        stmt = (
            delete(FileTransfer)
            .where(
                FileTransfer.upload_id == upload_id,
                FileTransfer.status == FileTransferStatusEnum.UPLOADING,
            )
            .returning(FileTransfer.file_id)
        )
        return await self._session.scalar(stmt) is not None

    async def get_undelivered_transfers(
        self, recipient_id: UUID
    ) -> list[FileTransferDTO]:
        stmt = (
            select(FileTransfer)
            .where(
                FileTransfer.recipient_id == recipient_id,
                FileTransfer.status == FileTransferStatusEnum.COMPLETED,
            )
            .order_by(FileTransfer.completed_at, FileTransfer.file_id)
        )
        results = await self._session.scalars(stmt)
        return [
            FileTransferDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def get_chunk(self, file_id: UUID, chunk_index: int) -> bytes | None:
        return await self._session.scalar(
            select(FileChunk.ciphertext).where(
                FileChunk.file_id == file_id,
                FileChunk.chunk_index == chunk_index,
            )
        )

    async def acknowledge_transfers(
        self, recipient_id: UUID, file_ids: Sequence[UUID]
    ) -> list[UUID]:
        stmt = (
            update(FileTransfer)
            .where(
                FileTransfer.recipient_id == recipient_id,
                FileTransfer.file_id.in_(file_ids),
                FileTransfer.status == FileTransferStatusEnum.COMPLETED,
            )
            .values(status=FileTransferStatusEnum.DELIVERED)
            .returning(FileTransfer.file_id)
        )
        results = await self._session.scalars(stmt)
        return list(results)
