from collections.abc import Sequence
from uuid import UUID

from src.adapters.database.dao.chat import ChatDAO
from src.adapters.database.dao.common import CommonDAO, error_handler
from src.adapters.database.dao.contact import ContactDAO
from src.adapters.database.dao.message import (
    CreateMessagePayloadDTO,
    MessageDAO,
)
from src.adapters.database.dto import (
    CreateContactDTO,
    CreateMessageFileDTO,
    CreateMessageTextDTO,
    MessageDTO,
)
from src.errors.error import ChatNotFoundError, ChatParticipantNotFoundError


class MessageService:
    def __init__(
        self,
        message_dao: MessageDAO,
        chat_dao: ChatDAO,
        contact_dao: ContactDAO,
        common_dao: CommonDAO,
    ):
        self._message_dao = message_dao
        self._chat_dao = chat_dao
        self._contact_dao = contact_dao
        self._common_dao = common_dao

    @error_handler
    async def add_text_message(self, message: CreateMessageTextDTO) -> MessageDTO:
        await self._ensure_blank_contact(message.sender_id, message.recipient_id)
        return await self._message_dao.add_text_message(message)

    @error_handler
    async def add_file_message(self, message: CreateMessageFileDTO) -> MessageDTO:
        return await self._message_dao.add_file_message(message)

    async def get_undelivered_messages(self, recipient_id: UUID) -> list[MessageDTO]:
        return await self._message_dao.get_undelivered_messages(recipient_id)

    @error_handler
    async def acknowledge_messages(
        self, recipient_id: UUID, message_ids: Sequence[UUID]
    ) -> int:
        return await self._message_dao.acknowledge_messages(recipient_id, message_ids)

    @error_handler
    async def add_chat_messages(
        self, messages: Sequence[CreateMessagePayloadDTO]
    ) -> list[MessageDTO]:
        if not messages:
            return []

        chat_id = messages[0].chat_id
        if chat_id is None or any(message.chat_id != chat_id for message in messages):
            raise ValueError("A chat message batch must contain one non-null chat_id")

        sender_ids = {message.sender_id for message in messages}
        if len(sender_ids) != 1:
            raise ValueError("A chat message batch must contain one sender_id")
        sender_id = next(iter(sender_ids))

        chat = await self._chat_dao.get_chat_by_id(chat_id)
        if chat is None:
            raise ChatNotFoundError("Chat not found", context={"chat_id": str(chat_id)})

        participants = await self._chat_dao.get_participants(chat_id)
        participant_ids = {participant.user_id for participant in participants}
        message_user_ids = {
            user_id
            for message in messages
            for user_id in (message.sender_id, message.recipient_id)
        }
        missing_participant_ids = message_user_ids - participant_ids
        if missing_participant_ids:
            raise ChatParticipantNotFoundError(
                "Every message sender and recipient must be a chat participant",
                context={
                    "chat_id": str(chat_id),
                    "user_ids": sorted(
                        str(user_id) for user_id in missing_participant_ids
                    ),
                },
            )

        for recipient_id in {message.recipient_id for message in messages}:
            await self._ensure_blank_contact(sender_id, recipient_id)

        return await self._message_dao.add_chat_messages(messages)

    async def _ensure_blank_contact(
        self,
        sender_id: UUID,
        recipient_id: UUID,
    ) -> None:
        if sender_id == recipient_id:
            return
        existing_contact = await self._contact_dao.get_contact_between_users(
            first_user_id=sender_id,
            second_user_id=recipient_id,
        )
        if existing_contact is not None:
            return
        await self._contact_dao.add_contact_request(
            CreateContactDTO(
                sender_id=sender_id,
                receiver_id=recipient_id,
            )
        )
