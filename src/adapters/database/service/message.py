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
    MessageReplyAccessDeniedError,
    MessageReplyNotFoundError,
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
        if message.reply_to_id is not None:
            reply_target = await self._message_dao.get_message_by_id(
                message.reply_to_id
            )
            if reply_target is None:
                raise MessageReplyNotFoundError(
                    "Reply target message not found",
                    context={"reply_to_id": str(message.reply_to_id)},
                )
            if reply_target.chat_id is not None or {
                reply_target.sender_id,
                reply_target.recipient_id,
            } != {message.sender_id, message.recipient_id}:
                raise MessageReplyAccessDeniedError(
                    "Reply target does not belong to the direct conversation",
                    context={"reply_to_id": str(message.reply_to_id)},
                )
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

    async def get_chat_reply_targets(
        self,
        chat_id: UUID,
        general_message_uuid: UUID,
        requester_id: UUID,
    ) -> list[MessageDTO]:
        chat = await self._chat_dao.get_chat_by_id(chat_id)
        if chat is None:
            raise ChatNotFoundError("Chat not found", context={"chat_id": str(chat_id)})
        participant = await self._chat_dao.get_participant(chat_id, requester_id)
        if participant is None or participant.left_at is not None:
            raise ChatParticipantNotFoundError(
                "User is not an active chat participant",
                context={"chat_id": str(chat_id), "user_id": str(requester_id)},
            )
        targets = await self._message_dao.get_chat_reply_targets(
            chat_id,
            general_message_uuid,
        )
        if not targets:
            raise MessageReplyNotFoundError(
                "Chat reply target not found",
                context={
                    "chat_id": str(chat_id),
                    "general_message_uuid": str(general_message_uuid),
                },
            )
        return targets

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

        general_message_uuids = {message.general_message_uuid for message in messages}
        if len(general_message_uuids) != 1 or None in general_message_uuids:
            raise ValueError(
                "A chat message batch must contain one general_message_uuid"
            )
        general_message_uuid = next(iter(general_message_uuids))
        assert general_message_uuid is not None

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

        reply_general_uuids = {
            message.reply_to_general_message_uuid for message in messages
        }
        if len(reply_general_uuids) != 1:
            raise ValueError(
                "A chat message batch must contain one reply target identity"
            )
        reply_general_message_uuid = next(iter(reply_general_uuids))
        if reply_general_message_uuid is None:
            if any(message.reply_to_id is not None for message in messages):
                raise MessageReplyAccessDeniedError(
                    "Chat reply target identity is missing"
                )
        else:
            reply_targets = await self._message_dao.get_chat_reply_targets(
                chat_id,
                reply_general_message_uuid,
            )
            if not reply_targets:
                raise MessageReplyNotFoundError(
                    "Chat reply target not found",
                    context={
                        "chat_id": str(chat_id),
                        "general_message_uuid": str(reply_general_message_uuid),
                    },
                )
            target_by_id = {target.id: target for target in reply_targets}
            historical_recipient_ids = {target.recipient_id for target in reply_targets}
            original_sender_ids = {target.sender_id for target in reply_targets}
            if len(original_sender_ids) != 1:
                raise MessageReplyAccessDeniedError(
                    "Chat reply target batch has inconsistent senders"
                )
            original_sender_id = next(iter(original_sender_ids))
            for message in messages:
                if message.reply_to_id is None:
                    if (
                        message.recipient_id in historical_recipient_ids
                        and message.recipient_id != original_sender_id
                    ):
                        raise MessageReplyAccessDeniedError(
                            "Recipient-specific chat reply target is missing",
                            context={
                                "recipient_id": str(message.recipient_id),
                                "general_message_uuid": str(reply_general_message_uuid),
                            },
                        )
                    continue
                target = target_by_id.get(message.reply_to_id)
                if target is None or target.recipient_id != message.recipient_id:
                    raise MessageReplyAccessDeniedError(
                        "Chat reply target does not belong to the recipient",
                        context={
                            "recipient_id": str(message.recipient_id),
                            "reply_to_id": str(message.reply_to_id),
                        },
                    )

        existing_messages = await self._message_dao.get_chat_messages_by_general_uuid(
            sender_id,
            chat_id,
            general_message_uuid,
        )
        if existing_messages:
            existing_by_id = {message.id: message for message in existing_messages}
            if len(existing_by_id) != len(messages) or any(
                (existing := existing_by_id.get(message.id)) is None
                or existing.recipient_id != message.recipient_id
                or existing.content != message.content
                or existing.ephemeral_public_key != message.ephemeral_public_key
                or existing.ephemeral_signature != message.ephemeral_signature
                or existing.reply_to_id != message.reply_to_id
                or existing.reply_to_general_message_uuid
                != message.reply_to_general_message_uuid
                for message in messages
            ):
                raise ChatMessageConflictError(
                    "General chat message UUID is already used by another batch",
                    context={
                        "chat_id": str(chat_id),
                        "general_message_uuid": str(general_message_uuid),
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
