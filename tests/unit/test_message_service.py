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
    MessageProcessingResultDTO,
)
from src.adapters.database.service.message import MessageService
from src.adapters.database.structures import ContactStatusEnum
from src.errors.error import (
    ChatMembershipConflictError,
    ChatMessageConflictError,
    MessageReplyAccessDeniedError,
    MessageReplyNotFoundError,
)


def _message(
    sender_id: UUID,
    recipient_id: UUID,
    chat_id: UUID | None,
    *,
    general_message_uuid: UUID | None = None,
    reply_to_id: UUID | None = None,
    reply_to_general_message_uuid: UUID | None = None,
) -> CreateMessageTextDTO:
    return CreateMessageTextDTO(
        general_message_uuid=general_message_uuid or chat_id,
        sender_id=sender_id,
        recipient_id=recipient_id,
        chat_id=chat_id,
        reply_to_id=reply_to_id,
        reply_to_general_message_uuid=reply_to_general_message_uuid,
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
    message_dao.get_chat_messages_by_general_uuid.return_value = []
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
    contact_dao.add_blank_contacts.assert_awaited_once()
    created_pairs = {
        (contact.sender_id, contact.receiver_id)
        for contact in contact_dao.add_blank_contacts.await_args.args[0]
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

    with pytest.raises(ChatMembershipConflictError, match="membership changed"):
        await service.add_chat_messages([_message(sender_id, recipient_id, chat_id)])

    message_dao.add_chat_messages.assert_not_awaited()
    contact_dao.add_blank_contacts.assert_not_awaited()
    common_dao.commit.assert_not_awaited()


async def test_add_chat_messages_rejects_duplicate_recipients_without_writes() -> None:
    chat_id = uuid4()
    sender_id = uuid4()
    recipient_id = uuid4()
    general_message_uuid = uuid4()
    messages = [
        _message(
            sender_id,
            recipient_id,
            chat_id,
            general_message_uuid=general_message_uuid,
        ),
        _message(
            sender_id,
            recipient_id,
            chat_id,
            general_message_uuid=general_message_uuid,
        ),
    ]
    service, message_dao, chat_dao, contact_dao, common_dao = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, sender_id)
    chat_dao.get_participants.return_value = [
        _participant(chat_id, sender_id),
        _participant(chat_id, recipient_id),
    ]

    with pytest.raises(ChatMembershipConflictError, match="must be unique"):
        await service.add_chat_messages(messages)

    message_dao.get_chat_messages_by_general_uuid.assert_not_awaited()
    contact_dao.add_blank_contacts.assert_not_awaited()
    message_dao.add_chat_messages.assert_not_awaited()
    common_dao.commit.assert_not_awaited()


async def test_add_chat_messages_returns_matching_idempotent_batch() -> None:
    chat_id = uuid4()
    sender_id = uuid4()
    recipient_id = uuid4()
    general_message_uuid = uuid4()
    message = _message(
        sender_id,
        recipient_id,
        chat_id,
        general_message_uuid=general_message_uuid,
    )
    existing = MessageDTO.model_validate(message)
    service, message_dao, chat_dao, contact_dao, common_dao = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, sender_id)
    chat_dao.get_participants.return_value = [
        _participant(chat_id, sender_id),
        _participant(chat_id, recipient_id),
    ]
    message_dao.get_chat_messages_by_general_uuid.return_value = [existing]

    result = await service.add_chat_messages([message])

    assert result == [existing]
    contact_dao.add_blank_contacts.assert_not_awaited()
    message_dao.add_chat_messages.assert_not_awaited()
    common_dao.commit.assert_awaited_once()


async def test_chat_reply_uses_general_fallback_for_original_author() -> None:
    chat_id = uuid4()
    original_sender_id = uuid4()
    replying_user_id = uuid4()
    other_recipient_id = uuid4()
    quoted_general_uuid = uuid4()
    new_general_uuid = uuid4()
    quoted_for_replying_user = MessageDTO.model_validate(
        _message(
            original_sender_id,
            replying_user_id,
            chat_id,
            general_message_uuid=quoted_general_uuid,
        )
    )
    quoted_for_other_recipient = MessageDTO.model_validate(
        _message(
            original_sender_id,
            other_recipient_id,
            chat_id,
            general_message_uuid=quoted_general_uuid,
        )
    )
    reply_for_original_author = _message(
        replying_user_id,
        original_sender_id,
        chat_id,
        general_message_uuid=new_general_uuid,
        reply_to_general_message_uuid=quoted_general_uuid,
    )
    reply_for_other_recipient = _message(
        replying_user_id,
        other_recipient_id,
        chat_id,
        general_message_uuid=new_general_uuid,
        reply_to_id=quoted_for_other_recipient.id,
        reply_to_general_message_uuid=quoted_general_uuid,
    )
    messages = [reply_for_original_author, reply_for_other_recipient]
    service, message_dao, chat_dao, _, _ = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, original_sender_id)
    chat_dao.get_participants.return_value = [
        _participant(chat_id, original_sender_id),
        _participant(chat_id, replying_user_id),
        _participant(chat_id, other_recipient_id),
    ]
    message_dao.get_chat_reply_targets.return_value = [
        quoted_for_replying_user,
        quoted_for_other_recipient,
    ]
    message_dao.add_chat_messages.return_value = [
        MessageDTO.model_validate(message) for message in messages
    ]

    result = await service.add_chat_messages(messages)

    assert result[0].reply_to_id is None
    assert result[0].reply_to_general_message_uuid == quoted_general_uuid
    assert result[1].reply_to_id == quoted_for_other_recipient.id


async def test_chat_reply_rejects_another_recipients_physical_target() -> None:
    chat_id = uuid4()
    original_sender_id = uuid4()
    replying_user_id = uuid4()
    other_recipient_id = uuid4()
    quoted_general_uuid = uuid4()
    quoted_for_replying_user = MessageDTO.model_validate(
        _message(
            original_sender_id,
            replying_user_id,
            chat_id,
            general_message_uuid=quoted_general_uuid,
        )
    )
    quoted_for_other_recipient = MessageDTO.model_validate(
        _message(
            original_sender_id,
            other_recipient_id,
            chat_id,
            general_message_uuid=quoted_general_uuid,
        )
    )
    invalid_reply = _message(
        replying_user_id,
        other_recipient_id,
        chat_id,
        general_message_uuid=uuid4(),
        reply_to_id=quoted_for_replying_user.id,
        reply_to_general_message_uuid=quoted_general_uuid,
    )
    reply_for_original_author = _message(
        replying_user_id,
        original_sender_id,
        chat_id,
        general_message_uuid=invalid_reply.general_message_uuid,
        reply_to_general_message_uuid=quoted_general_uuid,
    )
    service, message_dao, chat_dao, _, _ = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, original_sender_id)
    chat_dao.get_participants.return_value = [
        _participant(chat_id, original_sender_id),
        _participant(chat_id, replying_user_id),
        _participant(chat_id, other_recipient_id),
    ]
    message_dao.get_chat_reply_targets.return_value = [
        quoted_for_replying_user,
        quoted_for_other_recipient,
    ]

    with pytest.raises(
        MessageReplyAccessDeniedError,
        match="does not belong to the recipient",
    ):
        await service.add_chat_messages([reply_for_original_author, invalid_reply])

    message_dao.add_chat_messages.assert_not_awaited()


async def test_add_chat_messages_rejects_conflicting_general_message_uuid() -> None:
    chat_id = uuid4()
    sender_id = uuid4()
    recipient_id = uuid4()
    general_message_uuid = uuid4()
    message = _message(
        sender_id,
        recipient_id,
        chat_id,
        general_message_uuid=general_message_uuid,
    )
    existing = MessageDTO.model_validate(message).model_copy(
        update={"content": "different-ciphertext"}
    )
    service, message_dao, chat_dao, contact_dao, common_dao = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, sender_id)
    chat_dao.get_participants.return_value = [
        _participant(chat_id, sender_id),
        _participant(chat_id, recipient_id),
    ]
    message_dao.get_chat_messages_by_general_uuid.return_value = [existing]

    with pytest.raises(ChatMessageConflictError, match="already used"):
        await service.add_chat_messages([message])

    contact_dao.add_blank_contacts.assert_not_awaited()
    message_dao.add_chat_messages.assert_not_awaited()
    common_dao.commit.assert_not_awaited()


async def test_acknowledge_messages_commits_delivery_updates() -> None:
    service, message_dao, _, _, common_dao = _service()
    recipient_id = uuid4()
    results = [
        MessageProcessingResultDTO(message_id=uuid4(), failed=False),
        MessageProcessingResultDTO(message_id=uuid4(), failed=True),
    ]
    message_dao.acknowledge_messages.return_value = 2

    acknowledged = await service.acknowledge_messages(recipient_id, results)

    assert acknowledged == 2
    message_dao.acknowledge_messages.assert_awaited_once_with(recipient_id, results)
    common_dao.commit.assert_awaited_once()


async def test_get_failed_messages_reads_without_committing() -> None:
    service, message_dao, _, _, common_dao = _service()
    sender_id = uuid4()
    failed_message = _message(sender_id, uuid4(), None).model_copy(
        update={"is_delivered": True, "failed": True}
    )
    message_dao.get_failed_messages.return_value = [failed_message]

    messages = await service.get_failed_messages(sender_id)

    assert messages[0].failed is True
    message_dao.get_failed_messages.assert_awaited_once_with(sender_id)
    common_dao.commit.assert_not_awaited()


async def test_get_chat_reply_targets_requires_active_participant() -> None:
    chat_id = uuid4()
    requester_id = uuid4()
    general_message_uuid = uuid4()
    target = MessageDTO.model_validate(
        _message(
            uuid4(),
            requester_id,
            chat_id,
            general_message_uuid=general_message_uuid,
        )
    )
    service, message_dao, chat_dao, _, common_dao = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, target.sender_id)
    chat_dao.get_participant.return_value = _participant(chat_id, requester_id)
    message_dao.get_chat_reply_targets.return_value = [target]

    result = await service.get_chat_reply_targets(
        chat_id,
        general_message_uuid,
        requester_id,
    )

    assert result == [target]
    message_dao.get_chat_reply_targets.assert_awaited_once_with(
        chat_id,
        general_message_uuid,
    )
    common_dao.commit.assert_not_awaited()


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


async def test_add_text_message_accepts_reply_in_same_direct_conversation() -> None:
    sender_id = uuid4()
    recipient_id = uuid4()
    target = _message(recipient_id, sender_id, None)
    reply = _message(sender_id, recipient_id, None).model_copy(
        update={"reply_to_id": target.id}
    )
    service, message_dao, _, contact_dao, _ = _service()
    message_dao.get_message_by_id.return_value = MessageDTO.model_validate(target)
    message_dao.add_text_message.return_value = MessageDTO.model_validate(reply)
    contact_dao.get_contact_between_users.return_value = ContactDTO(
        id=uuid4(),
        sender_id=sender_id,
        receiver_id=recipient_id,
        status=ContactStatusEnum.ACCEPTED,
        created_at=datetime.now(UTC),
    )

    saved = await service.add_text_message(reply)

    assert saved.reply_to_id == target.id
    message_dao.get_message_by_id.assert_awaited_once_with(target.id)
    message_dao.add_text_message.assert_awaited_once_with(reply)


async def test_add_text_message_rejects_missing_reply_target() -> None:
    sender_id = uuid4()
    recipient_id = uuid4()
    reply = _message(sender_id, recipient_id, None).model_copy(
        update={"reply_to_id": uuid4()}
    )
    service, message_dao, _, contact_dao, _ = _service()
    message_dao.get_message_by_id.return_value = None

    with pytest.raises(MessageReplyNotFoundError):
        await service.add_text_message(reply)

    contact_dao.get_contact_between_users.assert_not_awaited()
    message_dao.add_text_message.assert_not_awaited()


@pytest.mark.parametrize("target_is_chat", [False, True])
async def test_add_text_message_rejects_reply_outside_direct_conversation(
    target_is_chat: bool,
) -> None:
    sender_id = uuid4()
    recipient_id = uuid4()
    other_user_id = uuid4()
    target = _message(
        sender_id,
        recipient_id if target_is_chat else other_user_id,
        uuid4() if target_is_chat else None,
    )
    reply = _message(sender_id, recipient_id, None).model_copy(
        update={"reply_to_id": target.id}
    )
    service, message_dao, _, contact_dao, _ = _service()
    message_dao.get_message_by_id.return_value = MessageDTO.model_validate(target)

    with pytest.raises(MessageReplyAccessDeniedError):
        await service.add_text_message(reply)

    contact_dao.get_contact_between_users.assert_not_awaited()
    message_dao.add_text_message.assert_not_awaited()
