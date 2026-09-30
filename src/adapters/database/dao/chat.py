from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.dto import (
    ChatDTO,
    ChatEventDTO,
    ChatParticipantDTO,
    CreateChatDTO,
    CreateChatEventDTO,
    CreateChatParticipantDTO,
    UpdateChatDTO,
)
from src.adapters.database.structures import Chat, ChatEvent, ChatParticipant


class ChatDAO:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_chat(self, chat: CreateChatDTO) -> ChatDTO:
        stmt = insert(Chat).values(**chat.model_dump()).returning(Chat)
        result = await self._session.scalar(stmt)
        assert result is not None
        return ChatDTO.model_validate(result, from_attributes=True)

    async def get_chat_by_id(self, chat_id: UUID) -> ChatDTO | None:
        result = await self._session.scalar(select(Chat).where(Chat.id == chat_id))
        if result is None:
            return None
        return ChatDTO.model_validate(result, from_attributes=True)

    async def get_chats_by_user_id(self, user_id: UUID) -> list[ChatDTO]:
        stmt = (
            select(Chat)
            .join(ChatParticipant, ChatParticipant.chat_id == Chat.id)
            .where(
                ChatParticipant.user_id == user_id,
                ChatParticipant.left_at.is_(None),
            )
            .order_by(Chat.created_at.desc(), Chat.id)
        )
        results = await self._session.scalars(stmt)
        return [
            ChatDTO.model_validate(result, from_attributes=True) for result in results
        ]

    async def update_chat(self, chat_id: UUID, chat: UpdateChatDTO) -> ChatDTO | None:
        stmt = (
            update(Chat)
            .where(Chat.id == chat_id)
            .values(**chat.model_dump())
            .returning(Chat)
        )
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return ChatDTO.model_validate(result, from_attributes=True)

    async def delete_chat(self, chat_id: UUID) -> bool:
        stmt = delete(Chat).where(Chat.id == chat_id).returning(Chat.id)
        return await self._session.scalar(stmt) is not None

    async def add_participant(
        self, participant: CreateChatParticipantDTO
    ) -> ChatParticipantDTO:
        stmt = (
            insert(ChatParticipant)
            .values(**participant.model_dump())
            .returning(ChatParticipant)
        )
        result = await self._session.scalar(stmt)
        assert result is not None
        return ChatParticipantDTO.model_validate(result, from_attributes=True)

    async def restore_participant(
        self, participant: CreateChatParticipantDTO
    ) -> ChatParticipantDTO:
        stmt = (
            update(ChatParticipant)
            .where(
                ChatParticipant.chat_id == participant.chat_id,
                ChatParticipant.user_id == participant.user_id,
            )
            .values(
                invited_by_user_id=participant.invited_by_user_id,
                joined_at=participant.joined_at,
                left_at=None,
            )
            .returning(ChatParticipant)
        )
        result = await self._session.scalar(stmt)
        assert result is not None
        return ChatParticipantDTO.model_validate(result, from_attributes=True)

    async def get_participant(
        self, chat_id: UUID, user_id: UUID
    ) -> ChatParticipantDTO | None:
        result = await self._session.scalar(
            select(ChatParticipant).where(
                ChatParticipant.chat_id == chat_id,
                ChatParticipant.user_id == user_id,
            )
        )
        if result is None:
            return None
        return ChatParticipantDTO.model_validate(result, from_attributes=True)

    async def get_participants(self, chat_id: UUID) -> list[ChatParticipantDTO]:
        stmt = (
            select(ChatParticipant)
            .where(
                ChatParticipant.chat_id == chat_id,
                ChatParticipant.left_at.is_(None),
            )
            .order_by(ChatParticipant.joined_at, ChatParticipant.user_id)
        )
        results = await self._session.scalars(stmt)
        return [
            ChatParticipantDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def delete_participant(
        self,
        chat_id: UUID,
        user_id: UUID,
        left_at: datetime,
    ) -> bool:
        stmt = (
            update(ChatParticipant)
            .where(
                ChatParticipant.chat_id == chat_id,
                ChatParticipant.user_id == user_id,
                ChatParticipant.left_at.is_(None),
            )
            .values(left_at=left_at)
            .returning(ChatParticipant.user_id)
        )
        return await self._session.scalar(stmt) is not None

    async def create_event(self, event: CreateChatEventDTO) -> ChatEventDTO:
        stmt = insert(ChatEvent).values(**event.model_dump()).returning(ChatEvent)
        result = await self._session.scalar(stmt)
        assert result is not None
        return ChatEventDTO.model_validate(result, from_attributes=True)

    async def get_events(
        self,
        chat_id: UUID,
        after: datetime | None = None,
        until: datetime | None = None,
    ) -> list[ChatEventDTO]:
        stmt = (
            select(ChatEvent)
            .where(ChatEvent.chat_id == chat_id)
            .order_by(ChatEvent.timestamp, ChatEvent.id)
        )
        if after is not None:
            stmt = stmt.where(ChatEvent.timestamp > after)
        if until is not None:
            stmt = stmt.where(ChatEvent.timestamp <= until)
        results = await self._session.scalars(stmt)
        return [
            ChatEventDTO.model_validate(result, from_attributes=True)
            for result in results
        ]
