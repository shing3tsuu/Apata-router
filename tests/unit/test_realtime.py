import json
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.adapters.realtime.broker import RealtimePublisher
from src.adapters.realtime.connection import RealtimeConnectionManager
from src.application.models.realtime import (
    RealtimeBrokerEvent,
    RealtimeEvent,
    RealtimePresenceUpdate,
)
from src.application.routers.realtime import (
    ACCESS_TOKEN_EXPIRED_CLOSE_CODE,
    ACCESS_TOKEN_EXPIRED_CLOSE_REASON,
    _receive_before_access_token_expiration,
)


def test_presence_update_command_validation() -> None:
    command = RealtimePresenceUpdate.model_validate(
        {"version": 1, "type": "presence_update", "online": True}
    )

    assert command.online is True

    with pytest.raises(ValidationError):
        RealtimePresenceUpdate.model_validate(
            {"version": 1, "type": "presence_update", "online": "yes"}
        )


async def test_expired_access_token_closes_established_websocket() -> None:
    websocket = AsyncMock()

    message = await _receive_before_access_token_expiration(
        websocket,
        datetime.now(UTC) - timedelta(seconds=1),
    )

    assert message is None
    websocket.receive_text.assert_not_awaited()
    websocket.close.assert_awaited_once_with(
        code=ACCESS_TOKEN_EXPIRED_CLOSE_CODE,
        reason=ACCESS_TOKEN_EXPIRED_CLOSE_REASON,
    )


async def test_websocket_message_is_received_before_token_expiration() -> None:
    websocket = AsyncMock()
    websocket.receive_text.return_value = '{"type":"presence_update"}'

    message = await _receive_before_access_token_expiration(
        websocket,
        datetime.now(UTC) + timedelta(seconds=10),
    )

    assert message == '{"type":"presence_update"}'
    websocket.close.assert_not_awaited()


async def test_connection_manager_tracks_multiple_sessions_per_user() -> None:
    user_id = uuid4()
    first_socket = AsyncMock()
    second_socket = AsyncMock()
    manager = RealtimeConnectionManager(logging.getLogger(__name__))

    assert await manager.connect(user_id, first_socket) is True
    assert await manager.connect(user_id, second_socket) is False
    assert await manager.connection_count(user_id) == 2

    assert await manager.disconnect(user_id, first_socket) is False
    assert await manager.disconnect(user_id, second_socket) is True
    assert await manager.connection_count(user_id) == 0


async def test_connection_manager_delivers_public_event_to_every_session() -> None:
    user_id = uuid4()
    first_socket = AsyncMock()
    second_socket = AsyncMock()
    manager = RealtimeConnectionManager(logging.getLogger(__name__))
    await manager.connect(user_id, first_socket)
    await manager.connect(user_id, second_socket)
    event = RealtimeEvent(
        type="message_available",
        payload={"message_id": str(uuid4())},
    )

    await manager.send_to_users(event, [user_id, user_id])

    expected = event.model_dump(mode="json")
    first_socket.send_json.assert_awaited_once_with(expected)
    second_socket.send_json.assert_awaited_once_with(expected)


async def test_publisher_keeps_recipients_out_of_public_payload() -> None:
    redis_client = AsyncMock()
    publisher = RealtimePublisher(redis_client, logging.getLogger(__name__))
    recipient_id = uuid4()

    published = await publisher.publish(
        "contact_changed",
        [recipient_id, recipient_id],
        {"action": "accepted"},
    )

    assert published is True
    channel, raw_event = redis_client.publish.await_args.args
    broker_event = json.loads(raw_event)
    assert channel == RealtimePublisher.CHANNEL
    assert broker_event["recipient_ids"] == [str(recipient_id)]
    assert broker_event["payload"] == {"action": "accepted"}
    public_payload = (
        RealtimeBrokerEvent.model_validate(broker_event)
        .public_event()
        .model_dump(mode="json")
    )
    assert "recipient_ids" not in public_payload
