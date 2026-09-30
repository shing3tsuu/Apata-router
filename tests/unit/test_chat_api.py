from datetime import UTC, datetime
from uuid import uuid4

from fastapi.routing import APIRoute

from src.adapters.database.dto import (
    ChatEventDTO,
    ChatParticipantChangeDTO,
    ChatParticipantDTO,
)
from src.adapters.database.structures import ChatEventTypeEnum
from src.application.routers.chat import (
    ChatAPI,
    _participant_change_response,
)


def _change(event_type: ChatEventTypeEnum) -> ChatParticipantChangeDTO:
    chat_id = uuid4()
    actor_id = uuid4()
    participant_id = uuid4()
    timestamp = datetime.now(UTC)
    return ChatParticipantChangeDTO(
        participant=ChatParticipantDTO(
            chat_id=chat_id,
            user_id=participant_id,
            invited_by_user_id=actor_id,
            joined_at=timestamp,
        ),
        event=ChatEventDTO(
            id=uuid4(),
            chat_id=chat_id,
            actor_id=actor_id,
            target_user_id=participant_id,
            event_type=event_type,
            timestamp=timestamp,
        ),
    )


def test_chat_api_exposes_current_client_routes() -> None:
    paths_and_methods = {
        (route.path, method)
        for route in ChatAPI().get_router().routes
        if isinstance(route, APIRoute)
        for method in route.methods or set()
    }

    assert ("/chats", "POST") in paths_and_methods
    assert ("/chats/{chat_id}", "DELETE") in paths_and_methods
    assert ("/chats/{chat_id}/participants", "POST") in paths_and_methods
    assert ("/chats/{chat_id}/participants/{user_id}", "DELETE") in paths_and_methods


def test_removed_participant_response_is_compatible_with_client_dto() -> None:
    change = _change(ChatEventTypeEnum.MEMBER_REMOVED)

    response = _participant_change_response(change, left_at=True)

    assert response.participant.left_at == change.event.timestamp
    assert response.event.user_id == change.event.actor_id
    assert response.event.event_type == "member_removed"


def test_added_participant_response_is_compatible_with_client_dto() -> None:
    change = _change(ChatEventTypeEnum.MEMBER_ADDED)

    response = _participant_change_response(change)

    assert response.participant.left_at is None
    assert response.event.event_type == "member_added"
