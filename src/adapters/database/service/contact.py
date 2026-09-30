from uuid import UUID

from src.adapters.database.dto import ContactDTO, CreateContactDTO, UpdateContactDTO
from src.adapters.database.structures import ContactStatusEnum
from src.errors.error import ContactAlreadyExistsError

from ..dao.common import CommonDAO, error_handler
from ..dao.contact import ContactDAO


class ContactService:
    def __init__(
        self,
        contact_dao: ContactDAO,
        common_dao: CommonDAO,
    ):
        self._contact_dao = contact_dao
        self._common_dao = common_dao

    @error_handler
    async def add_contact_request(self, contact: CreateContactDTO) -> ContactDTO:
        existing = await self._contact_dao.get_contact_between_users(
            first_user_id=contact.sender_id,
            second_user_id=contact.receiver_id,
        )
        if existing and existing.status is ContactStatusEnum.BLANK:
            updated = await self._contact_dao.update_contact_relation(
                contact_id=existing.id,
                contact=UpdateContactDTO(
                    sender_id=contact.sender_id,
                    receiver_id=contact.receiver_id,
                    status=ContactStatusEnum.PENDING,
                ),
            )
            assert updated is not None
            return updated
        if existing:
            raise ContactAlreadyExistsError(
                "A contact relation already exists between these users",
                context={
                    "sender_id": str(contact.sender_id),
                    "receiver_id": str(contact.receiver_id),
                },
            )
        return await self._contact_dao.add_contact_request(contact)

    @error_handler
    async def blacklist_contact(
        self,
        blocker_id: UUID,
        blocked_user_id: UUID,
    ) -> ContactDTO:
        existing = await self._contact_dao.get_contact_between_users(
            first_user_id=blocker_id,
            second_user_id=blocked_user_id,
        )
        if existing is None:
            return await self._contact_dao.add_contact_request(
                CreateContactDTO(
                    sender_id=blocker_id,
                    receiver_id=blocked_user_id,
                    status=ContactStatusEnum.BLACKLIST,
                )
            )

        updated = await self._contact_dao.update_contact_relation(
            contact_id=existing.id,
            contact=UpdateContactDTO(
                sender_id=blocker_id,
                receiver_id=blocked_user_id,
                status=ContactStatusEnum.BLACKLIST,
            ),
        )
        assert updated is not None
        return updated

    @error_handler
    async def get_contacts_by_user_id(
        self,
        user_id: UUID,
        after_id: UUID | None = None,
        limit: int | None = None,
    ) -> list[ContactDTO]:
        return await self._contact_dao.get_contacts_by_user_id(
            user_id=user_id,
            after_id=after_id,
            limit=limit,
        )

    @error_handler
    async def get_contact_by_id(self, contact_id: UUID) -> ContactDTO | None:
        return await self._contact_dao.get_contact_by_id(contact_id)

    @error_handler
    async def get_contacts_between_users(
        self, current_user_id: UUID, other_user_ids: list[UUID]
    ) -> dict[UUID, ContactDTO]:
        return await self._contact_dao.get_contacts_between_users(
            current_user_id=current_user_id,
            other_user_ids=other_user_ids,
        )

    @error_handler
    async def update_contact_request(
        self, contact_id: UUID, status: ContactStatusEnum
    ) -> ContactDTO | None:
        return await self._contact_dao.update_contact_request(
            contact_id=contact_id,
            status=status,
        )

    @error_handler
    async def delete_contact_request(self, contact_id: UUID) -> bool:
        return await self._contact_dao.delete_contact_request(contact_id)
