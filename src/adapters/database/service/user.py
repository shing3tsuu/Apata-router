from typing import overload
from uuid import UUID

from src.adapters.database.dto import (
    CreateUserDTO,
    UpdateUserDTO,
    UserDTO,
    UserWithStatusDTO,
)

from ..dao.common import CommonDAO, error_handler
from ..dao.user import UserDAO


class UserService:
    def __init__(
        self,
        user_dao: UserDAO,
        common_dao: CommonDAO,
    ):
        self._user_dao = user_dao
        self._common_dao = common_dao

    @error_handler
    async def create_user(self, user: CreateUserDTO) -> UserDTO:
        return await self._user_dao.create_user(user)

    @overload
    async def get_users_by_id(self, user_ids: UUID) -> UserDTO | None: ...

    @overload
    async def get_users_by_id(self, user_ids: list[UUID]) -> list[UserDTO]: ...

    async def get_users_by_id(
        self, user_ids: UUID | list[UUID]
    ) -> UserDTO | list[UserDTO] | None:
        if isinstance(user_ids, UUID):
            return await self._user_dao.get_user_by_id(user_ids)
        return await self._user_dao.get_users_by_ids(user_ids)

    @overload
    async def get_users_by_name(self, username: str, limit: None) -> UserDTO | None: ...

    @overload
    async def get_users_by_name(self, username: str, limit: int) -> list[UserDTO]: ...

    async def get_users_by_name(
        self, username: str, limit: int | None
    ) -> UserDTO | list[UserDTO] | None:
        if limit is None:
            return await self._user_dao.get_user_by_name(username)
        return await self._user_dao.get_users_by_name(username, limit)

    async def search_users_by_name(self, username: str) -> list[UserDTO]:
        return await self._user_dao.search_users_by_name(username)

    async def get_users_with_contact_status_by_ids(
        self, current_user_id: UUID, user_ids: list[UUID]
    ) -> list[UserWithStatusDTO]:
        return await self._user_dao.get_users_with_contact_status_by_ids(
            current_user_id, user_ids
        )

    @error_handler
    async def update_user(self, user_id: UUID, user: UpdateUserDTO) -> UserDTO | None:
        return await self._user_dao.update_user(user_id=user_id, user=user)

    @error_handler
    async def delete_user(self, user_id: UUID) -> bool:
        return await self._user_dao.delete_user(user_id)
