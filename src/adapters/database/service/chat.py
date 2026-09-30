from datetime import UTC, datetime
from uuid import UUID

from src.adapters.database.dao.chat import ChatDAO
from src.adapters.database.dao.common import CommonDAO, error_handler
from src.adapters.database.dao.user import UserDAO
from src.adapters.database.dto import (
    ChatDTO,
    ChatEventDTO,
    ChatParticipantChangeDTO,
    ChatParticipantDTO,
    CreateChatDTO,
    CreateChatEventDTO,
    CreateChatParticipantDTO,
    UpdateChatDTO,
    UserDTO,
)
from src.adapters.database.structures import ChatEventTypeEnum
from src.errors.error import (
    ChatNotFoundError,
    ChatParticipantAlreadyExistsError,
    ChatParticipantNotFoundError,
    ChatPermissionDeniedError,
    UserNotFoundError,
)


class ChatService:
    def __init__(
        self,
        chat_dao: ChatDAO,
        user_dao: UserDAO,
        common_dao: CommonDAO,
    ):
        self._chat_dao = chat_dao
        self._user_dao = user_dao
        self._common_dao = common_dao

    @error_handler
    async def create_chat(self, chat: CreateChatDTO) -> ChatDTO:
        await self._require_user(chat.owner_id)
        created_chat = await self._chat_dao.create_chat(chat)
        await self._chat_dao.add_participant(
            CreateChatParticipantDTO(
                chat_id=created_chat.id,
                user_id=created_chat.owner_id,
            )
        )
        await self._chat_dao.create_event(
            CreateChatEventDTO(
                chat_id=created_chat.id,
                actor_id=created_chat.owner_id,
                event_type=ChatEventTypeEnum.CREATED,
            )
        )
        return created_chat

    async def get_chat(self, chat_id: UUID, user_id: UUID) -> ChatDTO:
        chat = await self._require_chat(chat_id)
        await self._require_participant(chat_id, user_id)
        return chat

    async def get_chats_by_user_id(self, user_id: UUID) -> list[ChatDTO]:
        return await self._chat_dao.get_chats_by_user_id(user_id)

    async def get_participants(
        self, chat_id: UUID, requester_id: UUID
    ) -> list[ChatParticipantDTO]:
        await self._require_chat(chat_id)
        await self._require_participant(chat_id, requester_id)
        return await self._chat_dao.get_participants(chat_id)

    async def get_events(
        self,
        chat_id: UUID,
        requester_id: UUID,
        after: datetime | None = None,
    ) -> list[ChatEventDTO]:
        await self._require_chat(chat_id)
        participant = await self._chat_dao.get_participant(chat_id, requester_id)
        if participant is None:
            raise ChatParticipantNotFoundError(
                "User is not a current or former chat participant",
                context={"chat_id": str(chat_id), "user_id": str(requester_id)},
            )
        return await self._chat_dao.get_events(
            chat_id,
            after=after,
            until=participant.left_at,
        )

    @error_handler
    async def update_chat(
        self, chat_id: UUID, actor_id: UUID, chat: UpdateChatDTO
    ) -> ChatDTO:
        existing_chat = await self._require_chat(chat_id)
        self._require_owner(existing_chat, actor_id)
        updated_chat = await self._chat_dao.update_chat(chat_id, chat)
        assert updated_chat is not None
        await self._chat_dao.create_event(
            CreateChatEventDTO(
                chat_id=chat_id,
                actor_id=actor_id,
                event_type=ChatEventTypeEnum.NAME_CHANGED,
            )
        )
        return updated_chat

    @error_handler
    async def delete_chat(self, chat_id: UUID, actor_id: UUID) -> bool:
        chat = await self._require_chat(chat_id)
        self._require_owner(chat, actor_id)
        return await self._chat_dao.delete_chat(chat_id)

    @error_handler
    async def add_participant(
        self, chat_id: UUID, actor_id: UUID, user_id: UUID
    ) -> ChatParticipantChangeDTO:
        await self._require_chat(chat_id)
        await self._require_participant(chat_id, actor_id)
        await self._require_user(user_id)

        existing_participant = await self._chat_dao.get_participant(chat_id, user_id)
        if existing_participant is not None and existing_participant.left_at is None:
            raise ChatParticipantAlreadyExistsError(
                "User is already a chat participant",
                context={"chat_id": str(chat_id), "user_id": str(user_id)},
            )

        participant_data = CreateChatParticipantDTO(
            chat_id=chat_id,
            user_id=user_id,
            invited_by_user_id=actor_id,
        )
        if existing_participant is None:
            participant = await self._chat_dao.add_participant(participant_data)
            event_type = ChatEventTypeEnum.MEMBER_ADDED
        else:
            participant = await self._chat_dao.restore_participant(participant_data)
            event_type = ChatEventTypeEnum.MEMBER_JOINED
        event = await self._chat_dao.create_event(
            CreateChatEventDTO(
                chat_id=chat_id,
                actor_id=actor_id,
                target_user_id=user_id,
                event_type=event_type,
            )
        )
        return ChatParticipantChangeDTO(participant=participant, event=event)

    @error_handler
    async def remove_participant(
        self, chat_id: UUID, actor_id: UUID, user_id: UUID
    ) -> ChatParticipantChangeDTO:
        chat = await self._require_chat(chat_id)
        await self._require_participant(chat_id, actor_id)
        participant = await self._require_participant(chat_id, user_id)

        if user_id == chat.owner_id:
            raise ChatPermissionDeniedError(
                "The chat owner cannot be removed; delete the chat instead",
                context={"chat_id": str(chat_id), "user_id": str(user_id)},
            )
        if actor_id != chat.owner_id and participant.invited_by_user_id != actor_id:
            raise ChatPermissionDeniedError(
                "Only the chat owner or the participant's inviter can remove them",
                context={
                    "chat_id": str(chat_id),
                    "actor_id": str(actor_id),
                    "user_id": str(user_id),
                },
            )

        left_at = datetime.now(UTC)
        deleted = await self._chat_dao.delete_participant(
            chat_id,
            user_id,
            left_at,
        )
        assert deleted
        event = await self._chat_dao.create_event(
            CreateChatEventDTO(
                chat_id=chat_id,
                actor_id=actor_id,
                target_user_id=user_id,
                event_type=ChatEventTypeEnum.MEMBER_REMOVED,
                timestamp=left_at,
            )
        )
        return ChatParticipantChangeDTO(participant=participant, event=event)

    @error_handler
    async def leave_chat(
        self, chat_id: UUID, user_id: UUID
    ) -> ChatParticipantChangeDTO:
        chat = await self._require_chat(chat_id)
        participant = await self._require_participant(chat_id, user_id)
        if user_id == chat.owner_id:
            raise ChatPermissionDeniedError(
                "The chat owner cannot leave; delete the chat instead",
                context={"chat_id": str(chat_id), "user_id": str(user_id)},
            )

        left_at = datetime.now(UTC)
        deleted = await self._chat_dao.delete_participant(
            chat_id,
            user_id,
            left_at,
        )
        assert deleted
        event = await self._chat_dao.create_event(
            CreateChatEventDTO(
                chat_id=chat_id,
                actor_id=user_id,
                target_user_id=user_id,
                event_type=ChatEventTypeEnum.MEMBER_LEFT,
                timestamp=left_at,
            )
        )
        return ChatParticipantChangeDTO(participant=participant, event=event)

    async def _require_chat(self, chat_id: UUID) -> ChatDTO:
        chat = await self._chat_dao.get_chat_by_id(chat_id)
        if chat is None:
            raise ChatNotFoundError("Chat not found", context={"chat_id": str(chat_id)})
        return chat

    async def _require_user(self, user_id: UUID) -> UserDTO:
        user = await self._user_dao.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found", context={"user_id": str(user_id)})
        return user

    async def _require_participant(
        self, chat_id: UUID, user_id: UUID
    ) -> ChatParticipantDTO:
        participant = await self._chat_dao.get_participant(chat_id, user_id)
        if participant is None or participant.left_at is not None:
            raise ChatParticipantNotFoundError(
                "User is not a chat participant",
                context={"chat_id": str(chat_id), "user_id": str(user_id)},
            )
        return participant

    @staticmethod
    def _require_owner(chat: ChatDTO, actor_id: UUID) -> None:
        if chat.owner_id != actor_id:
            raise ChatPermissionDeniedError(
                "Only the chat owner can perform this operation",
                context={"chat_id": str(chat.id), "actor_id": str(actor_id)},
            )
