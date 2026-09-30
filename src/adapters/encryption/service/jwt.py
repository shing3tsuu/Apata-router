from uuid import UUID

from ..dao.jwt import JWTDAO


class JWTService:
    def __init__(self, jwt_dao: JWTDAO) -> None:
        self._jwt_dao = jwt_dao

    @property
    def access_token_expires_in_seconds(self) -> int:
        return self._jwt_dao.access_token_expires_in_seconds

    async def create_access_token(self, user_id: UUID) -> str:
        return await self._jwt_dao.create_access_token(user_id)

    async def get_access_token_user_id(self, token: str) -> UUID:
        return await self._jwt_dao.get_access_token_user_id(token)
