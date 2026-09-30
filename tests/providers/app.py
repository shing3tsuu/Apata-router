import os
from collections.abc import AsyncIterator

from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.orm import Session, SessionTransaction

from src.providers import AppProvider


class TestDBProvider(Provider):
    """Rollback all database changes when the test container is closed."""

    @provide(scope=Scope.APP, override=True)
    async def database_session(self) -> AsyncIterator[AsyncSession]:
        engine = create_async_engine(
            os.environ["DATABASE_URL"],
            echo=False,
            pool_size=1,
            max_overflow=0,
            pool_timeout=15,
            connect_args={"server_settings": {"jit": "off"}},
        )
        try:
            async with engine.connect() as connection:
                outer_transaction = await connection.begin()
                session = AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    autoflush=False,
                )
                await connection.begin_nested()
                _restart_savepoint_on_commit(connection, session)

                try:
                    yield session
                finally:
                    await session.close()
                    if outer_transaction.is_active:
                        await outer_transaction.rollback()
        finally:
            await engine.dispose()


def make_test_container() -> AsyncContainer:
    return make_async_container(
        AppProvider(),
        TestDBProvider(),
    )


def _restart_savepoint_on_commit(
    connection: AsyncConnection, session: AsyncSession
) -> None:
    @event.listens_for(session.sync_session, "after_transaction_end")
    def restart_savepoint(_session: Session, _transaction: SessionTransaction) -> None:
        if connection.closed:
            return
        if not connection.in_nested_transaction():
            sync_connection = connection.sync_connection
            if sync_connection is not None:
                sync_connection.begin_nested()
