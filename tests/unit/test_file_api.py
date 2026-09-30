from uuid import uuid4, uuid7

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from src.application.models.file import CreateFileUploadRequest
from src.application.routers.file import FileAPI


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
