import redis
import logging

from ..dao.user import AbstractUserDAO
from ..dao.common import AbstractCommonDAO
from src.adapters.database.dto import UserDTO, UserRequestDTO, UserWithStatusDTO

class UserService:
    __slots__ = (
        "_common_dao",
        "_user_dao",
        "_redis",
        "_logger",
    )

    def __init__(
            self,
            user_dao: AbstractUserDAO,
            common_dao: AbstractCommonDAO,
            redis_client: redis.Redis,
            logger: logging.Logger
    ):
        self._user_dao = user_dao
        self._common_dao = common_dao
        self._redis = redis_client
        self._logger = logger

    async def create_user(self, user: UserRequestDTO) -> UserDTO | None:
        try:
            result = await self._user_dao.create_user(user)
            await self._common_dao.commit()
            return result
        except Exception as e:
            self._logger.error(f"Error creating user: {e}")
            await self._common_dao.rollback()
            return None

    async def get_users_by_id(self, user_ids: int | list[int]) -> UserDTO | list[UserDTO] | None:
        try:
            if isinstance(user_ids, int):
                return await self._user_dao.get_user_by_id(user_ids)
            if isinstance(user_ids, list):
                return await self._user_dao.get_users_by_ids(user_ids)
        except Exception as e:
            self._logger.error(f"Error getting user by id: {e}")
            return None

    async def get_users_by_name(self, username: str, limit: int | None) -> UserDTO | list[UserDTO] | None:
        try:
            if limit is None:
                result = await self._user_dao.get_user_by_name(username)
                return result if result else None
            else:
                result = await self._user_dao.get_users_by_name(username, limit)
                return result if result else []
        except Exception as e:
            self._logger.error(f"Error getting users by name: {e}")
            return None if limit is None else []

    async def get_users_with_contact_status_by_ids(
            self,
            current_user_id: int,
            user_ids: list[int]
    ) -> list[UserWithStatusDTO]:
        try:
            return await self._user_dao.get_users_with_contact_status_by_ids(
                current_user_id,
                user_ids
            )
        except Exception as e:
            self._logger.error("Error getting users with contact status by ids: %s", e)
            return []

    async def update_user(self, user_id: int, user: UserRequestDTO) -> UserDTO | None:
        try:
            result = await self._user_dao.update_user(user_id=user_id, user=user)
            await self._common_dao.commit()
            return result
        except Exception as e:
            self._logger.error(f"Error updating user: {e}")
            await self._common_dao.rollback()
            return None

    async def delete_user(self, user_id: int) -> bool:
        try:
            result = await self._user_dao.delete_user(user_id)
            await self._common_dao.commit()
            return result
        except Exception as e:
            self._logger.error(f"Error deleting user: {e}")
            await self._common_dao.rollback()
            return False