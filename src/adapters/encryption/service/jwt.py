import hashlib
import math
from datetime import UTC, datetime
from uuid import UUID

import redis.asyncio as redis

from src.errors.error import RevokedAccessTokenError

from ..dao.jwt import JWTDAO


class JWTService:
    _REVOKED_TOKEN_PREFIX = "auth:revoked-token:"

    def __init__(self, jwt_dao: JWTDAO, redis_client: redis.Redis) -> None:
        self._jwt_dao = jwt_dao
        self._redis = redis_client

    @property
    def access_token_expires_in_seconds(self) -> int:
        return self._jwt_dao.access_token_expires_in_seconds

    async def create_access_token(self, user_id: UUID) -> str:
        return await self._jwt_dao.create_access_token(user_id)

    async def get_access_token_user_id(self, token: str) -> UUID:
        user_id = await self._jwt_dao.get_access_token_user_id(token)
        if await self.is_access_token_revoked(token):
            raise RevokedAccessTokenError("Access token has been revoked")
        return user_id

    async def get_access_token_expiration(self, token: str) -> datetime:
        return await self._jwt_dao.get_access_token_expiration(token)

    async def revoke_access_token(self, token: str) -> None:
        expires_at = await self._jwt_dao.get_access_token_expiration(token)
        remaining_seconds = math.ceil((expires_at - datetime.now(UTC)).total_seconds())
        if remaining_seconds <= 0:
            return
        await self._redis.set(
            self._revoked_token_key(token),
            "1",
            ex=remaining_seconds,
        )

    async def is_access_token_revoked(self, token: str) -> bool:
        return bool(await self._redis.exists(self._revoked_token_key(token)))

    @classmethod
    def _revoked_token_key(cls, token: str) -> str:
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        return f"{cls._REVOKED_TOKEN_PREFIX}{fingerprint}"
