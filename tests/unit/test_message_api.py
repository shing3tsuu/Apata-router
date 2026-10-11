from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from src.adapters.database.dto import MessageDTO
from src.adapters.database.structures import MessageContentMimeTypeEnum
from src.application.models.message import (
    MAX_ENCRYPTED_CHAT_BATCH_LENGTH,
    AcknowledgeMessagesRequest,
    MessageTextResponse,
    SendChatTextMessageRequest,
)
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
    assert ("/failed", "GET") in paths_and_methods
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
    assert response.general_message_uuid is None
    assert response.failed is None
    assert "content" not in response.model_dump()


def test_acknowledgement_requires_unique_message_ids() -> None:
    message_id = uuid4()

    with pytest.raises(ValidationError, match="must be unique"):
        AcknowledgeMessagesRequest.model_validate(
            {
                "results": [
                    {"message_id": message_id, "failed": False},
                    {"message_id": message_id, "failed": True},
                ]
            }
        )


def test_chat_batch_requires_unique_recipients_and_delivery_ids() -> None:
    recipient_id = uuid4()
    message_id = uuid4()
    base_request = {
        "general_message_uuid": uuid4(),
        "ephemeral_public_key": "ephemeral-public-key",
        "ephemeral_signature": "ephemeral-signature",
    }

    with pytest.raises(ValidationError, match="recipient IDs must be unique"):
        SendChatTextMessageRequest.model_validate(
            {
                **base_request,
                "deliveries": [
                    {
                        "recipient_id": recipient_id,
                        "message_id": message_id,
                        "message": "ciphertext-one",
                    },
                    {
                        "recipient_id": recipient_id,
                        "message_id": uuid4(),
                        "message": "ciphertext-two",
                    },
                ],
            }
        )

    with pytest.raises(ValidationError, match="delivery IDs must be unique"):
        SendChatTextMessageRequest.model_validate(
            {
                **base_request,
                "deliveries": [
                    {
                        "recipient_id": uuid4(),
                        "message_id": message_id,
                        "message": "ciphertext-one",
                    },
                    {
                        "recipient_id": uuid4(),
                        "message_id": message_id,
                        "message": "ciphertext-two",
                    },
                ],
            }
        )


def test_chat_batch_rejects_an_oversized_encrypted_payload() -> None:
    with pytest.raises(ValidationError, match="batch is too large"):
        SendChatTextMessageRequest.model_validate(
            {
                "general_message_uuid": uuid4(),
                "ephemeral_public_key": "ephemeral-public-key",
                "ephemeral_signature": "ephemeral-signature",
                "deliveries": [
                    {
                        "recipient_id": uuid4(),
                        "message_id": uuid4(),
                        "message": "x" * (MAX_ENCRYPTED_CHAT_BATCH_LENGTH // 32 + 1),
                    }
                    for _ in range(32)
                ],
            }
        )


def test_chat_batch_requires_general_identity_for_physical_reply_target() -> None:
    with pytest.raises(
        ValidationError,
        match="require reply_to_general_message_uuid",
    ):
        SendChatTextMessageRequest.model_validate(
            {
                "general_message_uuid": uuid4(),
                "ephemeral_public_key": "ephemeral-public-key",
                "ephemeral_signature": "ephemeral-signature",
                "deliveries": [
                    {
                        "recipient_id": uuid4(),
                        "message_id": uuid4(),
                        "reply_to_id": uuid4(),
                        "message": "encrypted-message",
                    }
                ],
            }
        )
