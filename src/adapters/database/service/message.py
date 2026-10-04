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
    MessageProcessingResultDTO,
)
from src.errors.error import (
    ChatMembershipConflictError,
    ChatMessageConflictError,
    ChatNotFoundError,
    ChatParticipantNotFoundError,
)


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
        self,
        recipient_id: UUID,
        results: Sequence[MessageProcessingResultDTO],
    ) -> int:
        return await self._message_dao.acknowledge_messages(recipient_id, results)

    async def get_failed_messages(self, sender_id: UUID) -> list[MessageDTO]:
        return await self._message_dao.get_failed_messages(sender_id)

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

        logical_message_ids = {message.logical_message_id for message in messages}
        if len(logical_message_ids) != 1 or None in logical_message_ids:
            raise ValueError("A chat message batch must contain one logical_message_id")
        logical_message_id = next(iter(logical_message_ids))
        assert logical_message_id is not None

        chat = await self._chat_dao.get_chat_by_id(chat_id)
        if chat is None:
            raise ChatNotFoundError("Chat not found", context={"chat_id": str(chat_id)})

        participants = await self._chat_dao.get_participants(chat_id)
        participant_ids = {participant.user_id for participant in participants}
        if sender_id not in participant_ids:
            raise ChatParticipantNotFoundError(
                "The message sender must be an active chat participant",
                context={
                    "chat_id": str(chat_id),
                    "user_id": str(sender_id),
                },
            )

        submitted_recipient_ids = [message.recipient_id for message in messages]
        if len(submitted_recipient_ids) != len(set(submitted_recipient_ids)):
            raise ChatMembershipConflictError(
                "Chat message recipients must be unique",
                context={"chat_id": str(chat_id)},
            )

        expected_recipient_ids = participant_ids - {sender_id}
        if set(submitted_recipient_ids) != expected_recipient_ids:
            raise ChatMembershipConflictError(
                "Chat membership changed while the message was being prepared",
                context={
                    "chat_id": str(chat_id),
                    "expected_recipient_ids": sorted(
                        str(user_id) for user_id in expected_recipient_ids
                    ),
                },
            )

        existing_messages = await self._message_dao.get_chat_messages_by_logical_id(
            sender_id,
            chat_id,
            logical_message_id,
        )
        if existing_messages:
            existing_by_id = {message.id: message for message in existing_messages}
            if len(existing_by_id) != len(messages) or any(
                (existing := existing_by_id.get(message.id)) is None
                or existing.recipient_id != message.recipient_id
                or existing.content != message.content
                or existing.ephemeral_public_key != message.ephemeral_public_key
                or existing.ephemeral_signature != message.ephemeral_signature
                for message in messages
            ):
                raise ChatMessageConflictError(
                    "Logical chat message ID is already used by another batch",
                    context={
                        "chat_id": str(chat_id),
                        "logical_message_id": str(logical_message_id),
                    },
                )
            return [existing_by_id[message.id] for message in messages]

        await self._contact_dao.add_blank_contacts(
            [
                CreateContactDTO(
                    sender_id=sender_id,
                    receiver_id=recipient_id,
                )
                for recipient_id in submitted_recipient_ids
            ]
        )

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
