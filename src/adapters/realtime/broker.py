import asyncio
import logging
from collections.abc import Iterable
from typing import Any
from uuid import UUID

import redis.asyncio as redis
from pydantic import ValidationError
from redis.exceptions import RedisError

from src.application.models.realtime import (
    RealtimeBrokerEvent,
    RealtimeEventType,
)

from .connection import RealtimeConnectionManager


class RealtimePublisher:
    CHANNEL = "apata.realtime.events"

    def __init__(self, redis_client: redis.Redis, logger: logging.Logger) -> None:
        self._redis = redis_client
        self._logger = logger

    async def publish(
        self,
        event_type: RealtimeEventType,
        recipient_ids: Iterable[UUID],
        payload: dict[str, Any] | None = None,
    ) -> bool:
        recipients = list(dict.fromkeys(recipient_ids))
        if not recipients:
            return True

        event = RealtimeBrokerEvent(
            type=event_type,
            recipient_ids=recipients,
            payload=payload or {},
        )
        try:
            await self._redis.publish(self.CHANNEL, event.model_dump_json())
            return True
        except RedisError:
            self._logger.exception(
                "Failed to publish realtime event type=%s id=%s",
                event.type,
                event.event_id,
            )
            return False


class RealtimeSubscriber:
    def __init__(
        self,
        redis_client: redis.Redis,
        connection_manager: RealtimeConnectionManager,
        logger: logging.Logger,
    ) -> None:
        self._redis = redis_client
        self._connection_manager = connection_manager
        self._logger = logger
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _listen(self) -> None:
        retry_delay = 1.0
        while True:
            try:
                async with self._redis.pubsub() as pubsub:
                    await pubsub.subscribe(RealtimePublisher.CHANNEL)
                    retry_delay = 1.0
                    async for message in pubsub.listen():
                        if message.get("type") != "message":
                            continue
                        raw_data = message.get("data")
                        if isinstance(raw_data, bytes):
                            raw_data = raw_data.decode("utf-8")
                        if not isinstance(raw_data, str):
                            continue
                        try:
                            event = RealtimeBrokerEvent.model_validate_json(raw_data)
                        except ValidationError:
                            self._logger.warning(
                                "Ignoring invalid realtime broker event",
                                exc_info=True,
                            )
                            continue
                        await self._connection_manager.send_to_users(
                            event.public_event(),
                            event.recipient_ids,
                        )
            except asyncio.CancelledError:
                raise
            except RedisError:
                self._logger.exception(
                    "Realtime Redis subscriber disconnected; retrying in %s seconds",
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)
