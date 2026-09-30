from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.adapters.database.dao.chat import ChatDAO
from src.adapters.database.dao.common import CommonDAO
from src.adapters.database.dao.user import UserDAO
from src.adapters.database.dto import (
    ChatDTO,
    ChatEventDTO,
    ChatParticipantDTO,
    CreateChatDTO,
    UserDTO,
)
from src.adapters.database.service.chat import ChatService
from src.adapters.database.structures import ChatEventTypeEnum, ChatParticipant
from src.errors.error import ChatPermissionDeniedError


def _user(user_id: UUID) -> UserDTO:
    return UserDTO(
        id=user_id,
        username=f"user_{user_id.hex[:8]}",
        ed_public_key="ed-key",
        ecdh_public_key="ecdh-key",
        ecdh_signature=None,
        last_seen=datetime.now(UTC),
        online=False,
    )


def _chat(chat_id: UUID, owner_id: UUID) -> ChatDTO:
    return ChatDTO(
        id=chat_id,
        owner_id=owner_id,
        name="Group chat",
        created_at=datetime.now(UTC),
    )


def _participant(
    chat_id: UUID,
    user_id: UUID,
    invited_by_user_id: UUID | None = None,
) -> ChatParticipantDTO:
    return ChatParticipantDTO(
        chat_id=chat_id,
        user_id=user_id,
        invited_by_user_id=invited_by_user_id,
        joined_at=datetime.now(UTC),
    )


def _event(
    chat_id: UUID,
    actor_id: UUID,
    event_type: ChatEventTypeEnum,
    target_user_id: UUID | None = None,
) -> ChatEventDTO:
    return ChatEventDTO(
        id=uuid4(),
        chat_id=chat_id,
        actor_id=actor_id,
        target_user_id=target_user_id,
        event_type=event_type,
        timestamp=datetime.now(UTC),
    )


def _service() -> tuple[ChatService, AsyncMock, AsyncMock, AsyncMock]:
    chat_dao = AsyncMock(spec=ChatDAO)
    user_dao = AsyncMock(spec=UserDAO)
    common_dao = AsyncMock(spec=CommonDAO)
    return (
        ChatService(
            chat_dao=chat_dao,
            user_dao=user_dao,
            common_dao=common_dao,
        ),
        chat_dao,
        user_dao,
        common_dao,
    )


async def test_create_chat_adds_owner_and_creation_event() -> None:
    owner_id = uuid4()
    chat_id = uuid4()
    service, chat_dao, user_dao, common_dao = _service()
    user_dao.get_user_by_id.return_value = _user(owner_id)
    chat_dao.create_chat.return_value = _chat(chat_id, owner_id)

    created = await service.create_chat(CreateChatDTO(owner_id=owner_id, name=" Chat "))

    assert created.id == chat_id
    participant = chat_dao.add_participant.await_args.args[0]
    event = chat_dao.create_event.await_args.args[0]
    assert participant.chat_id == chat_id
    assert participant.user_id == owner_id
    assert participant.invited_by_user_id is None
    assert event.event_type is ChatEventTypeEnum.CREATED
    assert event.actor_id == owner_id
    common_dao.commit.assert_awaited_once()


async def test_get_events_forwards_exclusive_after_timestamp() -> None:
    requester_id = uuid4()
    chat_id = uuid4()
    after = datetime.now(UTC)
    service, chat_dao, _, _ = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, requester_id)
    chat_dao.get_participant.return_value = _participant(chat_id, requester_id)
    chat_dao.get_events.return_value = []

    events = await service.get_events(chat_id, requester_id, after=after)

    assert events == []
    chat_dao.get_events.assert_awaited_once_with(
        chat_id,
        after=after,
        until=None,
    )


async def test_former_participant_reads_history_only_until_left_at() -> None:
    requester_id = uuid4()
    chat_id = uuid4()
    after = datetime.now(UTC)
    left_at = datetime.now(UTC)
    service, chat_dao, _, _ = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, requester_id)
    participant = _participant(chat_id, requester_id)
    participant.left_at = left_at
    chat_dao.get_participant.return_value = participant
    chat_dao.get_events.return_value = []

    events = await service.get_events(chat_id, requester_id, after=after)

    assert events == []
    chat_dao.get_events.assert_awaited_once_with(
        chat_id,
        after=after,
        until=left_at,
    )


def test_chat_participant_model_contains_inviter_column_from_migration() -> None:
    assert "invited_by_user_id" in ChatParticipant.__table__.c
    assert "left_at" in ChatParticipant.__table__.c


async def test_participant_can_invite_another_user_and_event_is_written() -> None:
    owner_id = uuid4()
    invited_user_id = uuid4()
    chat_id = uuid4()
    service, chat_dao, user_dao, common_dao = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, owner_id)
    chat_dao.get_participant.side_effect = [
        _participant(chat_id, owner_id),
        None,
    ]
    user_dao.get_user_by_id.return_value = _user(invited_user_id)
    chat_dao.add_participant.return_value = _participant(
        chat_id,
        invited_user_id,
        owner_id,
    )
    chat_dao.create_event.return_value = _event(
        chat_id,
        owner_id,
        ChatEventTypeEnum.MEMBER_ADDED,
        invited_user_id,
    )

    change = await service.add_participant(chat_id, owner_id, invited_user_id)

    assert change.participant.invited_by_user_id == owner_id
    creation = chat_dao.add_participant.await_args.args[0]
    event = chat_dao.create_event.await_args.args[0]
    assert creation.invited_by_user_id == owner_id
    assert event.event_type is ChatEventTypeEnum.MEMBER_ADDED
    assert event.target_user_id == invited_user_id
    common_dao.commit.assert_awaited_once()


async def test_former_participant_is_restored_with_joined_event() -> None:
    owner_id = uuid4()
    returning_user_id = uuid4()
    chat_id = uuid4()
    service, chat_dao, user_dao, common_dao = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, owner_id)
    former_participant = _participant(chat_id, returning_user_id, owner_id)
    former_participant.left_at = datetime.now(UTC)
    chat_dao.get_participant.side_effect = [
        _participant(chat_id, owner_id),
        former_participant,
    ]
    user_dao.get_user_by_id.return_value = _user(returning_user_id)
    chat_dao.restore_participant.return_value = _participant(
        chat_id,
        returning_user_id,
        owner_id,
    )
    chat_dao.create_event.return_value = _event(
        chat_id,
        owner_id,
        ChatEventTypeEnum.MEMBER_JOINED,
        returning_user_id,
    )

    change = await service.add_participant(chat_id, owner_id, returning_user_id)

    assert change.event.event_type is ChatEventTypeEnum.MEMBER_JOINED
    chat_dao.restore_participant.assert_awaited_once()
    chat_dao.add_participant.assert_not_awaited()
    common_dao.commit.assert_awaited_once()


async def test_inviter_can_remove_the_user_they_invited() -> None:
    owner_id = uuid4()
    inviter_id = uuid4()
    invited_user_id = uuid4()
    chat_id = uuid4()
    service, chat_dao, _, common_dao = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, owner_id)
    chat_dao.get_participant.side_effect = [
        _participant(chat_id, inviter_id),
        _participant(chat_id, invited_user_id, inviter_id),
    ]
    chat_dao.delete_participant.return_value = True
    chat_dao.create_event.return_value = _event(
        chat_id,
        inviter_id,
        ChatEventTypeEnum.MEMBER_REMOVED,
        invited_user_id,
    )

    change = await service.remove_participant(chat_id, inviter_id, invited_user_id)

    assert change.participant.user_id == invited_user_id
    event = chat_dao.create_event.await_args.args[0]
    assert event.event_type is ChatEventTypeEnum.MEMBER_REMOVED
    assert event.actor_id == inviter_id
    assert event.target_user_id == invited_user_id
    common_dao.commit.assert_awaited_once()


async def test_unrelated_member_cannot_remove_a_participant() -> None:
    owner_id = uuid4()
    actor_id = uuid4()
    inviter_id = uuid4()
    invited_user_id = uuid4()
    chat_id = uuid4()
    service, chat_dao, _, common_dao = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, owner_id)
    chat_dao.get_participant.side_effect = [
        _participant(chat_id, actor_id),
        _participant(chat_id, invited_user_id, inviter_id),
    ]

    with pytest.raises(ChatPermissionDeniedError, match="owner or the participant"):
        await service.remove_participant(chat_id, actor_id, invited_user_id)

    chat_dao.delete_participant.assert_not_awaited()
    chat_dao.create_event.assert_not_awaited()
    common_dao.commit.assert_not_awaited()


async def test_only_owner_can_delete_chat() -> None:
    owner_id = uuid4()
    other_user_id = uuid4()
    chat_id = uuid4()
    service, chat_dao, _, _ = _service()
    chat_dao.get_chat_by_id.return_value = _chat(chat_id, owner_id)

    with pytest.raises(ChatPermissionDeniedError, match="Only the chat owner"):
        await service.delete_chat(chat_id, other_user_id)

    chat_dao.delete_chat.assert_not_awaited()
