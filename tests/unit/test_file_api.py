from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4, uuid7

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from src.adapters.database.dto import FileTransferDTO
from src.adapters.database.service.file import FileService
from src.adapters.database.structures import FileTransferStatusEnum
from src.adapters.realtime import RealtimePublisher
from src.application.models.file import CreateFileUploadRequest
from src.application.routers.file import FileAPI, _complete_upload_and_notify
from src.errors.error import FileTransferIncompleteError


def test_file_api_exposes_client_routes() -> None:
    paths_and_methods = {
        (route.path, method)
        for route in FileAPI().get_router().routes
        if isinstance(route, APIRoute)
        for method in route.methods or set()
    }

    assert ("/files/uploads", "POST") in paths_and_methods
    assert ("/files/uploads/{upload_id}", "PATCH") in paths_and_methods
    assert ("/files/uploads/{upload_id}/complete", "POST") in paths_and_methods
    assert ("/files/undelivered", "GET") in paths_and_methods
    assert ("/files/ack", "POST") in paths_and_methods
    assert ("/files/{file_id}/chunks/{chunk_index}", "GET") in paths_and_methods


def test_file_upload_request_requires_uuidv7_file_id() -> None:
    with pytest.raises(ValidationError, match="UUIDv7"):
        CreateFileUploadRequest(
            file_id=uuid4(),
            recipient_id=uuid4(),
            message_id=uuid7(),
            total_size=0,
            chunk_size=1,
            encrypted_metadata="encrypted-metadata",
            ephemeral_public_key="ephemeral-key",
            ephemeral_signature="ephemeral-signature",
        )


async def test_completed_upload_publishes_message_available_after_completion() -> None:
    sender_id = uuid4()
    recipient_id = uuid4()
    transfer = FileTransferDTO(
        file_id=uuid7(),
        upload_id=uuid4(),
        message_id=uuid7(),
        sender_id=sender_id,
        recipient_id=recipient_id,
        total_size=10,
        chunk_size=10,
        offset=10,
        encrypted_metadata="encrypted-metadata",
        ephemeral_public_key="ephemeral-key",
        ephemeral_signature="ephemeral-signature",
        status=FileTransferStatusEnum.COMPLETED,
        created_at=datetime.now(UTC),
    )
    calls: list[str] = []
    file_service = AsyncMock(spec=FileService)
    realtime_publisher = AsyncMock(spec=RealtimePublisher)

    async def complete(*args: object) -> FileTransferDTO:
        calls.append("complete")
        return transfer

    async def publish(*args: object, **kwargs: object) -> bool:
        calls.append("publish")
        return True

    file_service.complete_upload.side_effect = complete
    realtime_publisher.publish.side_effect = publish

    result = await _complete_upload_and_notify(
        file_service=file_service,
        realtime_publisher=realtime_publisher,
        upload_id=transfer.upload_id,
        sender_id=sender_id,
    )

    assert result == transfer
    assert calls == ["complete", "publish"]
    realtime_publisher.publish.assert_awaited_once_with(
        "message_available",
        [recipient_id],
        {
            "message_id": str(transfer.message_id),
            "file_id": str(transfer.file_id),
            "sender_id": str(sender_id),
            "chat_id": None,
        },
    )


async def test_failed_upload_completion_does_not_publish_realtime_event() -> None:
    file_service = AsyncMock(spec=FileService)
    realtime_publisher = AsyncMock(spec=RealtimePublisher)
    file_service.complete_upload.side_effect = FileTransferIncompleteError(
        "Upload is incomplete"
    )

    with pytest.raises(FileTransferIncompleteError):
        await _complete_upload_and_notify(
            file_service=file_service,
            realtime_publisher=realtime_publisher,
            upload_id=uuid4(),
            sender_id=uuid4(),
        )

    realtime_publisher.publish.assert_not_awaited()
