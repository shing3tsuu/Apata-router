from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.adapters.database.dao.chat import ChatDAO
from src.adapters.database.dao.common import CommonDAO
from src.adapters.database.dao.contact import ContactDAO
from src.adapters.database.dao.message import MessageDAO
from src.adapters.database.dto import (
    ChatDTO,
    ChatParticipantDTO,
    ContactDTO,
    CreateContactDTO,
    CreateMessageTextDTO,
    MessageDTO,
)
from src.adapters.database.service.message import MessageService
from src.adapters.database.structures import ContactStatusEnum
from src.errors.error import ChatParticipantNotFoundError


def _message(
    sender_id: UUID,
    recipient_id: UUID,
    chat_id: UUID | None,
) -> CreateMessageTextDTO:
    return CreateMessageTextDTO(
        sender_id=sender_id,
        recipient_id=recipient_id,
        chat_id=chat_id,
        content="encrypted-text",
        ephemeral_public_key="ephemeral-key",
        ephemeral_signature="ephemeral-signature",
    )


def _chat(chat_id: UUID, owner_id: UUID) -> ChatDTO:
    return ChatDTO(
        id=chat_id,
        owner_id=owner_id,
        name="Chat",
        created_at=datetime.now(UTC),
    )


def _participant(chat_id: UUID, user_id: UUID) -> ChatParticipantDTO:
    return ChatParticipantDTO(
        chat_id=chat_id,
        user_id=user_id,
        joined_at=datetime.now(UTC),
    )


def _service() -> tuple[
    MessageService,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    message_dao = AsyncMock(spec=MessageDAO)
    chat_dao = AsyncMock(spec=ChatDAO)
    contact_dao = AsyncMock(spec=ContactDAO)
    common_dao = AsyncMock(spec=CommonDAO)
    return (
        MessageService(
            message_dao=message_dao,
            chat_dao=chat_dao,
            contact_dao=contact_dao,
            common_dao=common_dao,
        ),
        message_dao,
        chat_dao,
        contact_dao,
        common_dao,
    )


async def test_add_chat_messages_validates_batch_then_uses_dao_once() -> None:
    chat_id = uuid4()
    sender_id = uuid4()
    first_recipient_id = uuid4()
    second_recipient_id = uuid4()
    messages = [
        _message(sender_id, first_recipient_id, chat_id),
        _message(sender_id, second_recipient_id, chat_id),
    ]
    service, message_dao, chat_dao, contact_dao, common_dao = _service()
    contact_dao.get_contact_between_users.return_value = None
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, sender_id)
    chat_dao.get_participants.return_value = [
        _participant(chat_id, sender_id),
        _participant(chat_id, first_recipient_id),
        _participant(chat_id, second_recipient_id),
    ]
    message_dao.add_chat_messages.return_value = [
        MessageDTO.model_validate(message) for message in messages
    ]

    result = await service.add_chat_messages(messages)

    assert len(result) == 2
    message_dao.add_chat_messages.assert_awaited_once_with(messages)
    assert contact_dao.add_contact_request.await_count == 2
    created_pairs = {
        (call.args[0].sender_id, call.args[0].receiver_id)
        for call in contact_dao.add_contact_request.await_args_list
    }
    assert created_pairs == {
        (sender_id, first_recipient_id),
        (sender_id, second_recipient_id),
    }
    common_dao.commit.assert_awaited_once()


async def test_add_chat_messages_rejects_mixed_chat_ids_before_database_access() -> (
    None
):
    service, message_dao, chat_dao, _, common_dao = _service()
    sender_id = uuid4()
    messages = [
        _message(sender_id, uuid4(), uuid4()),
        _message(sender_id, uuid4(), uuid4()),
    ]

    with pytest.raises(ValueError, match="one non-null chat_id"):
        await service.add_chat_messages(messages)

    chat_dao.get_chat_by_id.assert_not_awaited()
    message_dao.add_chat_messages.assert_not_awaited()
    common_dao.commit.assert_not_awaited()


async def test_add_chat_messages_rejects_users_outside_chat() -> None:
    chat_id = uuid4()
    sender_id = uuid4()
    recipient_id = uuid4()
    service, message_dao, chat_dao, contact_dao, common_dao = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, sender_id)
    chat_dao.get_participants.return_value = [_participant(chat_id, sender_id)]

    with pytest.raises(
        ChatParticipantNotFoundError, match="must be a chat participant"
    ):
        await service.add_chat_messages([_message(sender_id, recipient_id, chat_id)])

    message_dao.add_chat_messages.assert_not_awaited()
    contact_dao.add_contact_request.assert_not_awaited()
    common_dao.commit.assert_not_awaited()


async def test_acknowledge_messages_commits_delivery_updates() -> None:
    service, message_dao, _, _, common_dao = _service()
    recipient_id = uuid4()
    message_ids = [uuid4(), uuid4()]
    message_dao.acknowledge_messages.return_value = 2

    acknowledged = await service.acknowledge_messages(recipient_id, message_ids)

    assert acknowledged == 2
    message_dao.acknowledge_messages.assert_awaited_once_with(recipient_id, message_ids)
    common_dao.commit.assert_awaited_once()


async def test_add_text_message_creates_blank_contact_once() -> None:
    sender_id = uuid4()
    recipient_id = uuid4()
    message = _message(sender_id, recipient_id, None)
    service, message_dao, _, contact_dao, common_dao = _service()
    contact_dao.get_contact_between_users.return_value = None
    message_dao.add_text_message.return_value = MessageDTO.model_validate(message)

    result = await service.add_text_message(message)

    assert result.sender_id == sender_id
    assert result.recipient_id == recipient_id
    contact_dao.add_contact_request.assert_awaited_once()
    created_contact = contact_dao.add_contact_request.await_args.args[0]
    assert isinstance(created_contact, CreateContactDTO)
    assert created_contact.sender_id == sender_id
    assert created_contact.receiver_id == recipient_id
    assert created_contact.status.value == "blank"
    common_dao.commit.assert_awaited_once()


async def test_add_text_message_preserves_existing_contact_status() -> None:
    sender_id = uuid4()
    recipient_id = uuid4()
    message = _message(sender_id, recipient_id, None)
    service, message_dao, _, contact_dao, _ = _service()
    contact_dao.get_contact_between_users.return_value = ContactDTO(
        id=uuid4(),
        sender_id=sender_id,
        receiver_id=recipient_id,
        status=ContactStatusEnum.ACCEPTED,
        created_at=datetime.now(UTC),
    )
    message_dao.add_text_message.return_value = MessageDTO.model_validate(message)

    await service.add_text_message(message)

    contact_dao.add_contact_request.assert_not_awaited()
