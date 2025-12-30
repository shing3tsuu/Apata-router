from abc import ABC, abstractmethod
from cgitb import reset

from sqlalchemy import select, delete, insert, update, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.dto import ContactRequestDTO, ContactDTO
from src.adapters.database.structures import ContactRequest

class AbstractContactDAO(ABC):
    @abstractmethod
    async def add_contact_request(self, contact: ContactRequestDTO) -> ContactDTO:
        raise NotImplementedError()

    @abstractmethod
    async def get_contacts_by_user_id(self, user_id: int) -> list[ContactDTO]:
        raise NotImplementedError()

    @abstractmethod
    async def get_contact_request(self, contact: ContactRequestDTO) -> ContactDTO | None:
        raise NotImplementedError()

    @abstractmethod
    async def get_contact_requests(self, contact: ContactRequestDTO) -> list[ContactDTO] | None:
        raise NotImplementedError()

    @abstractmethod
    async def update_contact_request(self, contact: ContactRequestDTO) -> ContactDTO | None:
        raise NotImplementedError()

class ContactDAO(AbstractContactDAO):
    __slots__ = "_session"

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add_contact_request(self, contact: ContactRequestDTO) -> ContactDTO:
        stmt = (
            insert(ContactRequest)
            .values(**contact.model_dump())
            .returning(ContactRequest)
        )
        result = await self._session.scalar(stmt)
        return ContactDTO.model_validate(result, from_attributes=True)

    async def get_contacts_by_user_id(self, user_id: int) -> list[ContactDTO]:
        stmt = (
            select(ContactRequest)
            .where(
                or_(
                    ContactRequest.sender_id == user_id,
                    ContactRequest.receiver_id == user_id
                )
            )
        )
        results = await self._session.scalars(stmt)
        return [
            ContactDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def get_contact_request(self, contact: ContactRequestDTO) -> ContactDTO | None:
        stmt = select(ContactRequest).where(
            ContactRequest.sender_id == contact.sender_id,
            ContactRequest.receiver_id == contact.receiver_id
        )
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return ContactDTO.model_validate(result, from_attributes=True)

    async def get_contact_requests(self, contact: ContactRequestDTO) -> list[ContactDTO] | None:
        stmt = (
            select(ContactRequest)
            .where(
                ContactRequest.receiver_id == contact.receiver_id,
                ContactRequest.status == contact.status
            )
        )
        results = await self._session.scalars(stmt)
        contacts = [
            ContactDTO.model_validate(result, from_attributes=True)
            for result in results
        ]
        return contacts if contacts else None

    async def update_contact_request(self, contact: ContactRequestDTO) -> ContactDTO | None:
        stmt = (
            update(ContactRequest).where(
                ContactRequest.sender_id == contact.sender_id,
                ContactRequest.receiver_id == contact.receiver_id
            )
            .values(status=contact.status)
            .returning(ContactRequest)
        )
        result = await self._session.scalar(stmt)
        return ContactDTO.model_validate(result, from_attributes=True)