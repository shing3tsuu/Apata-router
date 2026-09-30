from datetime import UTC, datetime
from uuid import uuid4

from fastapi.routing import APIRoute

from src.adapters.database.dto import MessageDTO
from src.adapters.database.structures import MessageContentMimeTypeEnum
from src.application.models.message import MessageTextResponse
from src.application.routers.message import MessageAPI


def test_message_api_exposes_current_and_fan_out_routes() -> None:
    paths_and_methods = {
        (route.path, method)
        for route in MessageAPI().get_router().routes
        if isinstance(route, APIRoute)
        for method in route.methods or set()
    }

    assert ("/send", "POST") in paths_and_methods
    assert ("/undelivered", "GET") in paths_and_methods
    assert ("/ack", "POST") in paths_and_methods
    assert ("/chats/{chat_id}/messages", "POST") in paths_and_methods


def test_text_message_response_uses_legacy_message_field_name() -> None:
    message = MessageDTO(
        id=uuid4(),
        sender_id=uuid4(),
        recipient_id=uuid4(),
        content="encrypted-text",
        file_mime_type=MessageContentMimeTypeEnum.TEXT,
        timestamp=datetime.now(UTC),
        ephemeral_public_key="ephemeral-public-key",
        ephemeral_signature="ephemeral-signature",
    )

    response = MessageTextResponse.model_validate(message)

    assert response.message == "encrypted-text"
    assert "content" not in response.model_dump()
