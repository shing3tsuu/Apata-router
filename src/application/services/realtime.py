import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.database.dao.common import CommonDAO
from src.adapters.database.dao.contact import ContactDAO
from src.adapters.database.dao.user import UserDAO
from src.adapters.database.dto import UpdateUserDTO
from src.adapters.database.service import ContactService, UserService


class RealtimePresenceService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: logging.Logger,
    ) -> None:
        self._session_factory = session_factory
        self._logger = logger

    async def set_presence(
        self,
        user_id: UUID,
        *,
        online: bool,
    ) -> tuple[datetime, list[UUID]]:
        changed_at = datetime.now(UTC)
        async with self._session_factory() as session:
            common_dao = CommonDAO(session)
            user_service = UserService(
                user_dao=UserDAO(session),
                common_dao=common_dao,
            )
            contact_service = ContactService(
                contact_dao=ContactDAO(session),
                common_dao=common_dao,
            )
            await user_service.update_user(
                user_id,
                UpdateUserDTO(online=online, last_seen=changed_at),
            )
            contacts = await contact_service.get_contacts_by_user_id(user_id)

        recipient_ids = list(
            dict.fromkeys(
                contact.receiver_id
                if contact.sender_id == user_id
                else contact.sender_id
                for contact in contacts
            )
        )
        self._logger.info(
            "Realtime presence changed: user=%s online=%s recipients=%s",
            user_id,
            online,
            len(recipient_ids),
        )
        return changed_at, recipient_ids
