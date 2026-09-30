from uuid import UUID

from sqlalchemy import and_, delete, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.dto import ContactDTO, CreateContactDTO, UpdateContactDTO
from src.adapters.database.structures import Contact, ContactStatusEnum


class ContactDAO:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add_contact_request(self, contact: CreateContactDTO) -> ContactDTO:
        stmt = insert(Contact).values(**contact.model_dump()).returning(Contact)
        result = await self._session.scalar(stmt)
        assert result is not None
        return ContactDTO.model_validate(result, from_attributes=True)

    async def get_contacts_by_user_id(
        self,
        user_id: UUID,
        after_id: UUID | None = None,
        limit: int | None = None,
    ) -> list[ContactDTO]:
        stmt = select(Contact).where(
            or_(Contact.sender_id == user_id, Contact.receiver_id == user_id)
        )
        if after_id is not None:
            cursor = await self._session.scalar(
                select(Contact).where(
                    Contact.id == after_id,
                    or_(
                        Contact.sender_id == user_id,
                        Contact.receiver_id == user_id,
                    ),
                )
            )
            if cursor is None:
                return []
            stmt = stmt.where(
                or_(
                    Contact.created_at > cursor.created_at,
                    and_(
                        Contact.created_at == cursor.created_at,
                        Contact.id > cursor.id,
                    ),
                )
            )
        stmt = stmt.order_by(Contact.created_at, Contact.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        results = await self._session.scalars(stmt)
        return [
            ContactDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def get_contact_request(
        self, sender_id: UUID, receiver_id: UUID
    ) -> ContactDTO | None:
        stmt = select(Contact).where(
            Contact.sender_id == sender_id, Contact.receiver_id == receiver_id
        )
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return ContactDTO.model_validate(result, from_attributes=True)

    async def get_contact_by_id(self, contact_id: UUID) -> ContactDTO | None:
        result = await self._session.scalar(
            select(Contact).where(Contact.id == contact_id)
        )
        if result is None:
            return None
        return ContactDTO.model_validate(result, from_attributes=True)

    async def get_contact_between_users(
        self, first_user_id: UUID, second_user_id: UUID
    ) -> ContactDTO | None:
        stmt = select(Contact).where(
            or_(
                (Contact.sender_id == first_user_id)
                & (Contact.receiver_id == second_user_id),
                (Contact.sender_id == second_user_id)
                & (Contact.receiver_id == first_user_id),
            )
        )
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return ContactDTO.model_validate(result, from_attributes=True)

    async def get_contact_requests(self, receiver_id: UUID) -> list[ContactDTO]:
        stmt = select(Contact).where(
            Contact.receiver_id == receiver_id,
            Contact.status == ContactStatusEnum.PENDING,
        )
        results = await self._session.scalars(stmt)
        return [
            ContactDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def get_contacts_between_users(
        self, current_user_id: UUID, other_user_ids: list[UUID]
    ) -> dict[UUID, ContactDTO]:
        if not other_user_ids:
            return {}

        stmt = select(Contact).where(
            or_(
                and_(
                    Contact.sender_id == current_user_id,
                    Contact.receiver_id.in_(other_user_ids),
                ),
                and_(
                    Contact.receiver_id == current_user_id,
                    Contact.sender_id.in_(other_user_ids),
                ),
            )
        )
        contacts = await self._session.scalars(stmt)
        result = {}
        for contact in contacts:
            other_user_id = (
                contact.receiver_id
                if contact.sender_id == current_user_id
                else contact.sender_id
            )
            result[other_user_id] = ContactDTO.model_validate(
                contact, from_attributes=True
            )
        return result

    async def update_contact_request(
        self, contact_id: UUID, status: ContactStatusEnum
    ) -> ContactDTO | None:
        stmt = (
            update(Contact)
            .where(Contact.id == contact_id)
            .values(status=status)
            .returning(Contact)
        )
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return ContactDTO.model_validate(result, from_attributes=True)

    async def update_contact_relation(
        self,
        contact_id: UUID,
        contact: UpdateContactDTO,
    ) -> ContactDTO | None:
        stmt = (
            update(Contact)
            .where(Contact.id == contact_id)
            .values(**contact.model_dump())
            .returning(Contact)
        )
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return ContactDTO.model_validate(result, from_attributes=True)

    async def delete_contact_request(self, contact_id: UUID) -> bool:
        stmt = delete(Contact).where(Contact.id == contact_id).returning(Contact.id)
        return await self._session.scalar(stmt) is not None
