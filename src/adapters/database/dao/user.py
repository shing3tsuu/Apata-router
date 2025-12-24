from abc import ABC, abstractmethod

from sqlalchemy import select, delete, insert, update, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.dto import UserRequestDTO, UserDTO, UserWithStatusDTO
from src.adapters.database.structures import User, ContactRequest

class AbstractUserDAO(ABC):
    @abstractmethod
    async def create_user(self, user: UserRequestDTO) -> UserDTO:
        raise NotImplementedError()

    @abstractmethod
    async def get_user_by_id(self, user_id: int) -> UserDTO | None:
        raise NotImplementedError()

    @abstractmethod
    async def get_users_by_ids(self, user_ids: list[int]) -> list[UserDTO]:
        raise NotImplementedError()

    @abstractmethod
    async def get_user_by_name(self, username: str) -> UserDTO | None:
        raise NotImplementedError()

    @abstractmethod
    async def get_users_by_name(self, username: str, limit: int) -> list[UserDTO] | None:
        raise NotImplementedError()

    @abstractmethod
    async def get_users_with_contact_status_by_ids(
            self,
            current_user_id: int,
            user_ids: list[int]
    ) -> list[UserDTO]:
        raise NotImplementedError()

    @abstractmethod
    async def update_user(self, user_id: int, user: UserRequestDTO) -> UserDTO | None:
        raise NotImplementedError()

    @abstractmethod
    async def delete_user(self, user_id: int) -> bool:
        raise NotImplementedError()

class UserDAO(AbstractUserDAO):
    __slots__ = "_session"

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_user(self, user: UserRequestDTO) -> UserDTO:
        existing_user = await self._session.scalar(
            select(User).where(User.username == user.username)
        )
        if existing_user:
            raise ValueError(f"User with this username: {user.username} already exists")
        stmt = (
            insert(User)
            .values(**user.model_dump())
            .returning(User)
        )
        result = await self._session.scalar(stmt)
        return UserDTO.model_validate(result, from_attributes=True)

    async def get_user_by_id(self, user_id: int) -> UserDTO | None:
        stmt = select(User).where(User.id == user_id)
        result = await self._session.scalar(stmt)
        return UserDTO.model_validate(result, from_attributes=True)

    async def get_users_by_ids(self, user_ids: list[int]) -> list[UserDTO]:
        stmt = select(User).where(User.id.in_(user_ids))
        results = await self._session.scalars(stmt)
        return [
            UserDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def get_user_by_name(self, username: str) -> UserDTO | None:
        stmt = select(User).where(User.username == username)
        result = await self._session.scalar(stmt)
        if result is None:
            return None
        return UserDTO.model_validate(result, from_attributes=True)

    async def get_users_by_name(self, username: str, limit: int) -> list[UserDTO] | None:
        pattern = f"%{username}%"
        stmt = select(User).where(User.username.ilike(pattern)).limit(limit)
        results = await self._session.scalars(stmt)
        return [
            UserDTO.model_validate(result, from_attributes=True)
            for result in results
        ]

    async def get_users_with_contact_status_by_ids(
        self,
        current_user_id: int,
        user_ids: list[int]
    ) -> list[UserDTO]:
        stmt = select(User).where(User.id.in_(user_ids))
        users = await self._session.scalars(stmt)

        contact_stmt = select(ContactRequest).where(
            or_(
                and_(
                    ContactRequest.sender_id == current_user_id,
                    ContactRequest.receiver_id.in_(user_ids)
                ),
                and_(
                    ContactRequest.sender_id.in_(user_ids),
                    ContactRequest.receiver_id == current_user_id
                )
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
            status = contact_dict.get(user.id, 'none')
            result_users.append(
                UserWithStatusDTO(
                    id=user.id,
                    username=user.username,
                    ecdsa_public_key=user.ecdsa_public_key,
                    ecdh_public_key=user.ecdh_public_key,
                    last_seen=user.last_seen,
                    status=status,
                    online=user.online
                )
            )

        return [
            UserWithStatusDTO.model_validate(result, from_attributes=True)
            for result in result_users
        ]

    async def update_user(self, user_id: int, user: UserRequestDTO) -> UserDTO | None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(**user.model_dump(exclude_unset=True))
            .returning(User)
            )
        result = await self._session.scalar(stmt)
        return UserDTO.model_validate(result, from_attributes=True)

    async def delete_user(self, user_id: int) -> bool:
        stmt = delete(User).where(User.id == user_id)
        result = await self._session.scalar(stmt)
        if result.rowcount > 0:
            return True
        else:
            return False