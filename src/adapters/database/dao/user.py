from uuid import UUID

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.dto import (
    CreateUserDTO,
    UpdateUserDTO,
    UserDTO,
    UserWithStatusDTO,
)
from src.adapters.database.structures import Contact, ContactStatusEnum, User
from src.errors.error import UserAlreadyExistsError


class UserDAO:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_user(self, user: CreateUserDTO) -> UserDTO:
        existing_user = await self._session.scalar(
            select(User).where(User.username == user.username)
        )
        if existing_user:
            raise UserAlreadyExistsError(
                f"User with username {user.username!r} already exists"
            )
        stmt = insert(User).values(**user.model_dump()).returning(User)
        result = await self._session.scalar(stmt)
        assert result is not None
        return UserDTO.model_validate(result)

    async def get_user_by_id(self, user_id: UUID) -> UserDTO | None:
        stmt = select(User).where(User.id == user_id)
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return UserDTO.model_validate(result)

    async def get_users_by_ids(self, user_ids: list[UUID]) -> list[UserDTO]:
        stmt = select(User).where(User.id.in_(user_ids))
        results = await self._session.scalars(stmt)
        return [UserDTO.model_validate(result) for result in results]

    async def get_user_by_name(self, username: str) -> UserDTO | None:
        stmt = select(User).where(User.username == username)
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return UserDTO.model_validate(result)

    async def get_users_by_name(self, username: str, limit: int) -> list[UserDTO]:
        pattern = f"%{username}%"
        stmt = select(User).where(User.username.ilike(pattern)).limit(limit)
        results = await self._session.scalars(stmt)
        return [UserDTO.model_validate(result) for result in results]

    async def search_users_by_name(self, username: str) -> list[UserDTO]:
        pattern = f"%{username}%"
        stmt = (
            select(User)
            .where(User.username.ilike(pattern))
            .order_by(func.lower(User.username))
        )
        results = await self._session.scalars(stmt)
        return [UserDTO.model_validate(result) for result in results]

    async def get_users_with_contact_status_by_ids(
        self, current_user_id: UUID, user_ids: list[UUID]
    ) -> list[UserWithStatusDTO]:
        stmt = select(User).where(User.id.in_(user_ids))
        users = await self._session.scalars(stmt)

        contact_stmt = select(Contact).where(
            or_(
                and_(
                    Contact.sender_id == current_user_id,
                    Contact.receiver_id.in_(user_ids),
                ),
                and_(
                    Contact.sender_id.in_(user_ids),
                    Contact.receiver_id == current_user_id,
                ),
            )
        )
        contacts = await self._session.scalars(contact_stmt)
        contact_dict = {}
        for contact in contacts:
            if contact.sender_id == current_user_id:
                contact_dict[contact.receiver_id] = contact.status
            else:
                contact_dict[contact.sender_id] = contact.status

        result_users = []
        for user in users:
            status = ContactStatusEnum(
                contact_dict.get(user.id, ContactStatusEnum.BLANK)
            )
            result_users.append(
                UserWithStatusDTO(
                    id=user.id,
                    username=user.username,
                    ed_public_key=user.ed_public_key,
                    ecdh_public_key=user.ecdh_public_key,
                    ecdh_signature=user.ecdh_signature,
                    last_seen=user.last_seen,
                    status=status,
                    online=user.online,
                )
            )

        return [UserWithStatusDTO.model_validate(result) for result in result_users]

    async def update_user(self, user_id: UUID, user: UpdateUserDTO) -> UserDTO | None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(**user.model_dump(exclude_unset=True))
            .returning(User)
        )
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return UserDTO.model_validate(result)

    async def delete_user(self, user_id: UUID) -> bool:
        stmt = delete(User).where(User.id == user_id).returning(User.id)
        return await self._session.scalar(stmt) is not None
