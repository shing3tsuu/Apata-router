from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from dishka import make_async_container
from jose import jwt

from src.adapters.encryption.service.jwt import JWTService
from src.errors.error import InvalidAccessTokenTypeError, MissingAccessTokenSubjectError
from src.providers import AppProvider


@pytest_asyncio.fixture
async def jwt_service(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[JWTService]:
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    container = make_async_container(AppProvider())
    try:
        async with container() as request_container:
            yield await request_container.get(JWTService)
    finally:
        await container.close()


async def test_create_and_validate_access_token(jwt_service: JWTService) -> None:
    user_id = uuid4()
    token = await jwt_service.create_access_token(user_id=user_id)

    assert await jwt_service.get_access_token_user_id(token) == user_id


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
