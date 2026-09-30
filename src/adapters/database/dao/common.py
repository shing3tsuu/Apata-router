from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, Protocol, TypeVar, cast

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.errors.error import DatabaseError

T = TypeVar("T")


class CommonDAO:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class HasCommonDAO(Protocol):
    _common_dao: CommonDAO


def error_handler(
    func: Callable[..., Awaitable[T]],
) -> Callable[..., Awaitable[T]]:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        service = cast(HasCommonDAO, args[0])
        try:
            result = await func(*args, **kwargs)
            await service._common_dao.commit()
            return result
        except SQLAlchemyError as error:
            await service._common_dao.rollback()
            raise DatabaseError(
                f"SQLAlchemy error in {func.__name__}",
                original_error=error,
            ) from error

    return wrapper
