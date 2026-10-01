from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.adapters.database.dto import CreateMessageDTO
from src.adapters.database.structures import (
    MessageContentMimeTypeEnum,
    MessageContentTypeEnum,
)


def _base_message() -> dict[str, object]:
    return {
        "sender_id": uuid4(),
        "recipient_id": uuid4(),
        "ephemeral_public_key": "ephemeral-key",
        "ephemeral_signature": "ephemeral-signature",
    }


def test_text_message_dto_accepts_ciphertext() -> None:
    message = CreateMessageDTO.model_validate(
        {**_base_message(), "content": "encrypted-text"}
    )

    assert message.content == "encrypted-text"
    assert message.file_content is None
    assert message.file_mime_type is MessageContentMimeTypeEnum.TEXT
    assert message.failed is None


def test_file_message_dto_accepts_encrypted_bytes_and_original_metadata() -> None:
    message = CreateMessageDTO.model_validate(
        {
            **_base_message(),
            "content_type": MessageContentTypeEnum.IMAGE,
            "file_name": "photo",
            "file_content": b"encrypted-image-bytes",
            "file_size": 1024,
            "file_mime_type": MessageContentMimeTypeEnum.PNG,
        }
    )

    assert message.file_content == b"encrypted-image-bytes"
    assert message.file_size == 1024


@pytest.mark.parametrize(
    ("content", "file_content"),
    [(None, None), ("encrypted-text", b"encrypted-file")],
)
def test_message_dto_requires_exactly_one_payload(
    content: str | None,
    file_content: bytes | None,
) -> None:
    with pytest.raises(ValidationError, match="exactly one payload"):
        CreateMessageDTO.model_validate(
            {
                **_base_message(),
                "content": content,
                "file_content": file_content,
                "file_name": "file" if file_content is not None else None,
                "file_size": 1 if file_content is not None else None,
            }
        )
