from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.dto import (
    CreateMessageFileDTO,
    CreateMessageTextDTO,
    MessageDTO,
)
from src.adapters.database.structures import Message

CreateMessagePayloadDTO = CreateMessageTextDTO | CreateMessageFileDTO


class MessageDAO:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add_text_message(self, message: CreateMessageTextDTO) -> MessageDTO:
        return await self._add_message(message)

    async def add_file_message(self, message: CreateMessageFileDTO) -> MessageDTO:
        return await self._add_message(message)

    async def add_chat_messages(
        self, messages: Sequence[CreateMessagePayloadDTO]
    ) -> list[MessageDTO]:
        """Persist all encrypted fan-out deliveries in one SQL INSERT statement."""
        if not messages:
            return []

        stmt = (
            insert(Message)
            .values([message.model_dump() for message in messages])
            .returning(Message)
        )
        results = await self._session.scalars(stmt)
        return [
            MessageDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def get_undelivered_messages(self, recipient_id: UUID) -> list[MessageDTO]:
        stmt = (
            select(Message)
            .where(
                Message.recipient_id == recipient_id,
                Message.is_delivered.is_(False),
            )
            .order_by(Message.timestamp, Message.id)
        )
        results = await self._session.scalars(stmt)
        return [
            MessageDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def acknowledge_messages(
        self, recipient_id: UUID, message_ids: Sequence[UUID]
    ) -> int:
        stmt = (
            update(Message)
            .where(
                Message.recipient_id == recipient_id,
                Message.id.in_(message_ids),
                Message.is_delivered.is_(False),
            )
            .values(is_delivered=True)
        )
        result = await self._session.execute(stmt)
        return cast(CursorResult[object], result).rowcount or 0

    async def _add_message(self, message: CreateMessagePayloadDTO) -> MessageDTO:
        stmt = insert(Message).values(**message.model_dump()).returning(Message)
        result = await self._session.scalar(stmt)
        assert result is not None
        return MessageDTO.model_validate(result, from_attributes=True)
