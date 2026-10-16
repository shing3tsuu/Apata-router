import asyncio
from datetime import UTC, datetime, timedelta
from typing import final
from uuid import UUID, uuid4

from jose import jwt

from src.errors.error import InvalidAccessTokenTypeError, MissingAccessTokenSubjectError


@final
class JWTDAO:
    def __init__(
        self, algorithm: str, access_token_expire_minutes: int, secret_key: str
    ) -> None:
        self._access_token_expire_minutes = access_token_expire_minutes
        self._secret_key = secret_key
        self._algorithm = algorithm

    @property
    def access_token_expires_in_seconds(self) -> int:
        return self._access_token_expire_minutes * 60

    async def create_access_token(self, user_id: UUID) -> str:
        loop = asyncio.get_running_loop()
        token = await loop.run_in_executor(None, self._create_access_token, user_id)
        return token

    async def get_access_token_user_id(self, token: str) -> UUID:
        loop = asyncio.get_running_loop()
        user_id = await loop.run_in_executor(
            None, self._get_access_token_user_id, token
        )
        return user_id

    async def get_access_token_expiration(self, token: str) -> datetime:
        loop = asyncio.get_running_loop()
        expiration = await loop.run_in_executor(
            None,
            self._get_access_token_expiration,
            token,
        )
        return expiration

    def _create_access_token(self, user_id: UUID) -> str:
        expires_delta = timedelta(minutes=self._access_token_expire_minutes)
        expire = datetime.now(UTC) + expires_delta

        payload = {
            "sub": str(user_id),
            "exp": expire,
            "type": "access",
            "iat": datetime.now(UTC),
            "jti": str(uuid4()),
        }
        token = jwt.encode(payload, self._secret_key, algorithm=self._algorithm)
        return token

    def _get_access_token_user_id(self, token: str) -> UUID:
        payload = self._decode_access_token(token)

        user_id = payload.get("sub")
        if user_id is None:
            raise MissingAccessTokenSubjectError("Access token has no subject")

        return UUID(user_id)

    def _get_access_token_expiration(self, token: str) -> datetime:
        payload = self._decode_access_token(token)
        expiration = payload.get("exp")
        if (
            not isinstance(expiration, (int, float))
            or isinstance(expiration, bool)
        ):
            raise TypeError("Access token expiration must be a numeric timestamp")
        return datetime.fromtimestamp(expiration, tz=UTC)

    def _decode_access_token(self, token: str) -> dict:
        payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])

        if payload.get("type") != "access":
            raise InvalidAccessTokenTypeError("JWT is not an access token")
        return payload
