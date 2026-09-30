import asyncio
import logging
from collections.abc import Iterable
from uuid import UUID

from fastapi import WebSocket

from src.application.models.realtime import RealtimeEvent


class RealtimeConnectionManager:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._connections: dict[UUID, dict[int, WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: UUID, websocket: WebSocket) -> bool:
        await websocket.accept()
        async with self._lock:
            user_connections = self._connections.setdefault(user_id, {})
            first_connection = not user_connections
            user_connections[id(websocket)] = websocket
        return first_connection

    async def disconnect(self, user_id: UUID, websocket: WebSocket) -> bool:
        async with self._lock:
            user_connections = self._connections.get(user_id)
            if user_connections is None:
                return False
            removed = user_connections.pop(id(websocket), None)
            if user_connections:
                return False
            self._connections.pop(user_id, None)
            return removed is not None

    async def send_to_users(
        self,
        event: RealtimeEvent,
        recipient_ids: Iterable[UUID],
    ) -> None:
        async with self._lock:
            sockets = [
                (user_id, websocket)
                for user_id in set(recipient_ids)
                for websocket in self._connections.get(user_id, {}).values()
            ]

        payload = event.model_dump(mode="json")
        for user_id, websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                self._logger.warning(
                    "Realtime delivery failed for user=%s event=%s",
                    user_id,
                    event.event_id,
                    exc_info=True,
                )

    async def connection_count(self, user_id: UUID) -> int:
        async with self._lock:
            return len(self._connections.get(user_id, {}))
