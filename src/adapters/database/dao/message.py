from abc import ABC, abstractmethod

from sqlalchemy import select, delete, insert, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.dto import MessageRequestDTO, MessageDTO
from src.adapters.database.structures import Message

class AbstractMessageDAO(ABC):
    @abstractmethod
    async def add_message(self, message: MessageRequestDTO) -> MessageDTO:
        raise NotImplementedError()

    @abstractmethod
    async def get_undelivered_messages(self, recipient_id: int) -> list[MessageDTO]:
        raise NotImplementedError()

    @abstractmethod
    async def mark_as_delivered(self, message_id: int) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def get_message_by_id(self, message_id: int) -> MessageDTO | None:
        raise NotImplementedError()

class MessageDAO(AbstractMessageDAO):
    __slots__ = "_session"

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add_message(self, message: MessageRequestDTO) -> MessageDTO:
        stmt = (
            insert(Message)
            .values(**message.model_dump())
            .returning(Message)
        )
        result = await self._session.scalar(stmt)
        return MessageDTO.model_validate(result, from_attributes=True)


    async def get_undelivered_messages(self, recipient_id: int) -> list[MessageDTO]:
        stmt = select(Message).where(
            Message.recipient_id == recipient_id,
            Message.is_delivered == False
        )
        results = await self._session.scalars(stmt)
        return [
            MessageDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def mark_as_delivered(self, message_id: int) -> bool:
        try:
            stmt = (
                update(Message)
                .where(Message.id == message_id)
                .values(is_delivered=True)
            )
            result = await self._session.execute(stmt)
            rowcount = result.rowcount
            return rowcount > 0
        except Exception as e:
            self._logger.error(f"Error marking message {message_id} as delivered: {e}")
            return False

    async def get_message_by_id(self, message_id: int) -> MessageDTO | None:
        stmt = select(Message).where(Message.id == message_id)
        result = await self._session.scalar(stmt)
        return MessageDTO.model_validate(result, from_attributes=True)