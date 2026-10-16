from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt

from src.adapters.encryption.dao.jwt import JWTDAO
from src.adapters.encryption.service.jwt import JWTService
from src.errors.error import (
    InvalidAccessTokenTypeError,
    MissingAccessTokenSubjectError,
    RevokedAccessTokenError,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        assert ex > 0
        self.values[key] = value

    async def exists(self, key: str) -> int:
        return int(key in self.values)


@pytest.fixture
def jwt_service() -> JWTService:
    return JWTService(
        jwt_dao=JWTDAO(
            algorithm="HS256",
            access_token_expire_minutes=480,
            secret_key="test-secret",
        ),
        redis_client=FakeRedis(),  # type: ignore[arg-type]
    )


async def test_create_and_validate_access_token(jwt_service: JWTService) -> None:
    user_id = uuid4()
    token = await jwt_service.create_access_token(user_id=user_id)

    assert await jwt_service.get_access_token_user_id(token) == user_id


async def test_access_token_exposes_its_expiration(
    jwt_service: JWTService,
) -> None:
    issued_after = datetime.now(UTC)
    token = await jwt_service.create_access_token(user_id=uuid4())

    expiration = await jwt_service.get_access_token_expiration(token)

    assert expiration.tzinfo is UTC
    expected_expiration = issued_after + timedelta(
        seconds=jwt_service.access_token_expires_in_seconds
    )
    assert abs(expiration - expected_expiration) <= timedelta(seconds=1)


async def test_access_tokens_for_same_user_have_unique_session_identity(
    jwt_service: JWTService,
) -> None:
    user_id = uuid4()

    first = await jwt_service.create_access_token(user_id)
    second = await jwt_service.create_access_token(user_id)

    assert first != second


async def test_revoked_access_token_is_rejected(jwt_service: JWTService) -> None:
    token = await jwt_service.create_access_token(user_id=uuid4())

    await jwt_service.revoke_access_token(token)

    assert await jwt_service.is_access_token_revoked(token) is True
    with pytest.raises(RevokedAccessTokenError):
        await jwt_service.get_access_token_user_id(token)


async def test_reject_non_access_token(jwt_service: JWTService) -> None:
    token = jwt.encode(
        {"sub": "42", "type": "refresh"},
        "test-secret",
        algorithm="HS256",
    )

    with pytest.raises(InvalidAccessTokenTypeError):
        await jwt_service.get_access_token_user_id(token)


async def test_reject_access_token_without_subject(jwt_service: JWTService) -> None:
    token = jwt.encode(
        {"type": "access"},
        "test-secret",
        algorithm="HS256",
    )

    with pytest.raises(MissingAccessTokenSubjectError):
        await jwt_service.get_access_token_user_id(token)
