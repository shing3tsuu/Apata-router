from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession


class AbstractCommonDAO(ABC):
    @abstractmethod
    async def commit(self):
        """
        SqlAlchemy commit
        :return:
        """
        raise NotImplementedError()

    @abstractmethod
    async def rollback(self):
        """
        SqlAlchemy rollback
        :return:
        """
        raise NotImplementedError()


class CommonDAO(AbstractCommonDAO):
    __slots__ = "_session"

    def __init__(self, session: AsyncSession):
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()