import redis
import logging

from ..dao.message import AbstractMessageDAO
from ..dao.common import AbstractCommonDAO
from src.adapters.database.dto import MessageDTO, MessageRequestDTO

class MessageService:
    __slots__ = (
        "_common_dao",
        "_message_dao",
        "_redis",
        "_logger",
    )

    def __init__(
            self,
            message_dao: AbstractMessageDAO,
            common_dao: AbstractCommonDAO,
            redis_client: redis.Redis,
            logger: logging.Logger
    ):
        self._message_dao = message_dao
        self._common_dao = common_dao
        self._redis = redis_client
        self._logger = logger

    async def add_message(self, message: MessageRequestDTO) -> MessageDTO | None:
        try:
            result = await self._message_dao.add_message(message)
            await self._common_dao.commit()
            return result
        except Exception as e:
            self._logger.error(f"Error adding message: {e}")
            await self._common_dao.rollback()
            return None

    async def get_undelivered_messages(self, recipient_id: int) -> list[MessageDTO]:
        try:
            return await self._message_dao.get_undelivered_messages(recipient_id)
        except Exception as e:
            self._logger.error(f"Error getting undelivered messages: {e}")
            return []

    async def mark_as_delivered(self, message_id: int) -> None:
        try:
            await self._message_dao.mark_as_delivered(message_id)
            await self._common_dao.commit()
        except Exception as e:
            self._logger.error(f"Error marking message as delivered: {e}")
            await self._common_dao.rollback()

    async def get_message_by_id(self, message_id: int) -> MessageDTO | None:
        try:
            return await self._message_dao.get_message_by_id(message_id)
        except Exception as e:
            self._logger.error(f"Error getting message by id: {e}")
            return None