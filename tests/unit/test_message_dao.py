from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.dao.message import MessageDAO
from src.adapters.database.dto import (
    CreateMessageFileDTO,
    CreateMessageTextDTO,
    MessageProcessingResultDTO,
)
from src.adapters.database.structures import (
    MessageContentMimeTypeEnum,
    MessageContentTypeEnum,
)


def _text_message(*, chat_id: UUID | None = None) -> CreateMessageTextDTO:
    return CreateMessageTextDTO(
        sender_id=uuid4(),
        recipient_id=uuid4(),
        chat_id=chat_id,
        content="encrypted-text",
        ephemeral_public_key="ephemeral-key",
        ephemeral_signature="ephemeral-signature",
    )


def _file_message(*, chat_id: UUID | None = None) -> CreateMessageFileDTO:
    return CreateMessageFileDTO(
        sender_id=uuid4(),
        recipient_id=uuid4(),
        chat_id=chat_id,
        content_type=MessageContentTypeEnum.IMAGE,
        file_name="encrypted-photo",
        file_content=b"encrypted-file",
        file_size=1024,
        file_mime_type=MessageContentMimeTypeEnum.PNG,
        ephemeral_public_key="ephemeral-key",
        ephemeral_signature="ephemeral-signature",
    )


async def test_add_text_message_uses_single_returning_insert() -> None:
    session = AsyncMock(spec=AsyncSession)
    message = _text_message()
    session.scalar.return_value = message

    result = await MessageDAO(session).add_text_message(message)

    assert result.id == message.id
    session.scalar.assert_awaited_once()
    session.scalars.assert_not_awaited()


async def test_add_file_message_uses_single_returning_insert() -> None:
    session = AsyncMock(spec=AsyncSession)
    message = _file_message()
    session.scalar.return_value = message

    result = await MessageDAO(session).add_file_message(message)

    assert result.file_content == b"encrypted-file"
    session.scalar.assert_awaited_once()


async def test_add_chat_messages_inserts_fan_out_batch_with_one_database_call() -> None:
    session = AsyncMock(spec=AsyncSession)
    chat_id = uuid4()
    messages: list[CreateMessageTextDTO | CreateMessageFileDTO] = [
        _text_message(chat_id=chat_id),
        _file_message(chat_id=chat_id),
    ]
    session.scalars.return_value = messages

    result = await MessageDAO(session).add_chat_messages(messages)

    assert [message.id for message in result] == [message.id for message in messages]
    session.scalars.assert_awaited_once()
    session.scalar.assert_not_awaited()


async def test_get_undelivered_messages_reads_recipient_inbox() -> None:
    session = AsyncMock(spec=AsyncSession)
    message = _text_message()
    session.scalars.return_value = [message]

    result = await MessageDAO(session).get_undelivered_messages(message.recipient_id)

    assert [item.id for item in result] == [message.id]
    session.scalars.assert_awaited_once()


async def test_acknowledge_messages_updates_only_recipient_messages() -> None:
    session = AsyncMock(spec=AsyncSession)
    successful_result = MagicMock()
    successful_result.rowcount = 1
    failed_result = MagicMock()
    failed_result.rowcount = 1
    session.execute.side_effect = [successful_result, failed_result]
    recipient_id = uuid4()
    successful_message_id = uuid4()
    failed_message_id = uuid4()

    acknowledged = await MessageDAO(session).acknowledge_messages(
        recipient_id,
        [
            MessageProcessingResultDTO(
                message_id=successful_message_id,
                failed=False,
            ),
            MessageProcessingResultDTO(
                message_id=failed_message_id,
                failed=True,
            ),
        ],
    )

    assert acknowledged == 2
    assert session.execute.await_count == 2


async def test_get_failed_messages_reads_sender_outbox() -> None:
    session = AsyncMock(spec=AsyncSession)
    message = _text_message()
    failed_message = message.model_copy(update={"is_delivered": True, "failed": True})
    session.scalars.return_value = [failed_message]

    result = await MessageDAO(session).get_failed_messages(message.sender_id)

    assert [item.id for item in result] == [message.id]
    assert result[0].failed is True
    session.scalars.assert_awaited_once()
