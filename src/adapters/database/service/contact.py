import redis
import logging

from ..dao.contact import AbstractContactDAO
from ..dao.common import AbstractCommonDAO
from src.adapters.database.dto import ContactDTO, ContactRequestDTO

class ContactService:
    __slots__ = (
        "_contact_dao",
        "_common_dao",
        "_redis",
        "_logger",
    )

    def __init__(
            self,
            contact_dao: AbstractContactDAO,
            common_dao: AbstractCommonDAO,
            redis_client: redis.Redis,
            logger: logging.Logger
    ):
        self._contact_dao = contact_dao
        self._common_dao = common_dao
        self._redis = redis_client
        self._logger = logger

    async def add_contact_request(self, contact: ContactRequestDTO) -> ContactDTO | None:
        try:
            existing = await self._contact_dao.get_contact_request(contact)
            if existing:
                raise ValueError("Contact request already exists")
            result = await self._contact_dao.add_contact_request(contact)
            await self._common_dao.commit()
            return result
        except Exception as e:
            self._logger.error(f"Error adding contact request: {e}")
            await self._common_dao.rollback()
            return None

    async def get_contacts_by_user_id(self, user_id: int) -> list[ContactDTO]:
        try:
            return await self._contact_dao.get_contacts_by_user_id(user_id)
        except Exception as e:
            self._logger.error(f"Error getting contacts by user id: {e}")
            return []

    async def get_contact_requests(self, contact: ContactRequestDTO, is_all: bool) -> ContactDTO | list[
        ContactDTO] | None:
        try:
            if is_all:
                result = await self._contact_dao.get_contact_requests(contact)
                return result
            else:
                result = await self._contact_dao.get_contact_request(contact)
                return result
        except Exception as e:
            self._logger.error(f"Error getting contact requests: {e}")
            return None

    async def update_contact_request(self, contact: ContactRequestDTO) -> ContactDTO | None:
        try:
            result = await self._contact_dao.update_contact_request(contact)
            await self._common_dao.commit()
            return result
        except Exception as e:
            self._logger.error(f"Error updating contact request: {e}")
            await self._common_dao.rollback()
            return None