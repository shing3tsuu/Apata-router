import asyncio
import redis
import logging

from typing import AsyncIterable
from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import Config, load_config

from src.adapters.database.structures import Base
from src.adapters.database.dao import (
    AbstractCommonDAO, CommonDAO,
    AbstractUserDAO, UserDAO,
    AbstractContactDAO, ContactDAO,
    AbstractMessageDAO, MessageDAO
)
from src.adapters.database.service import (
    UserService,
    ContactService,
    MessageService
)

from src.adapters.api.routers import AuthAPI, ContactAPI, MessageAPI

class AppProvider(Provider):
    scope = Scope.APP

    @provide(scope=Scope.APP)
    def get_config(self) -> Config:
        return load_config(".env")

    @provide(scope=Scope.APP)
    def get_logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    @provide(scope=Scope.APP)
    async def get_redis(self, config: Config) -> redis.Redis:
        return redis.Redis(host=config.redis.host, port=config.redis.port, db=0)

    @provide(scope=Scope.APP)
    async def database(self, config: Config) -> async_sessionmaker:
        engine = create_async_engine(
            f"postgresql+asyncpg://{config.db.user}:{config.db.password}@{config.db.host}:{config.db.port}/{config.db.name}",
            pool_size=50,
            pool_timeout=15,
            pool_recycle=1500,
            pool_pre_ping=True,
            max_overflow=15,
            connect_args={
                "server_settings": {"jit": "off"}
            },
        )
        # async with engine.begin() as conn:
        #     await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, autoflush=False, expire_on_commit=False)

    @provide(scope=Scope.REQUEST)
    async def new_connection(self, sessionmaker: async_sessionmaker) -> AsyncIterable[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    async def common_dao(self, session: AsyncSession) -> AbstractCommonDAO:
        return CommonDAO(session=session)

    @provide(scope=Scope.REQUEST)
    async def user_dao(self, session: AsyncSession) -> AbstractUserDAO:
        return UserDAO(session=session)

    @provide(scope=Scope.REQUEST)
    async def contact_dao(self, session: AsyncSession) -> AbstractContactDAO:
        return ContactDAO(session=session)

    @provide(scope=Scope.REQUEST)
    async def message_dao(self, session: AsyncSession) -> AbstractMessageDAO:
        return MessageDAO(session=session)

    @provide(scope=Scope.REQUEST)
    async def user_service(
            self,
            user_dao: AbstractUserDAO,
            common_dao: AbstractCommonDAO,
            redis_client: redis.Redis,
            logger: logging.Logger
    ) -> UserService:
        return UserService(
            user_dao=user_dao,
            common_dao=common_dao,
            redis_client=redis_client,
            logger=logger
        )

    @provide(scope=Scope.REQUEST)
    async def contact_service(
            self,
            contact_dao: AbstractContactDAO,
            common_dao: AbstractCommonDAO,
            redis_client: redis.Redis,
            logger: logging.Logger
    ) -> ContactService:
        return ContactService(
            contact_dao=contact_dao,
            common_dao=common_dao,
            redis_client=redis_client,
            logger=logger
        )

    @provide(scope=Scope.REQUEST)
    async def message_service(
            self,
            message_dao: AbstractMessageDAO,
            common_dao: AbstractCommonDAO,
            redis_client: redis.Redis,
            logger: logging.Logger
    ) -> MessageService:
        return MessageService(
            message_dao=message_dao,
            common_dao=common_dao,
            redis_client=redis_client,
            logger=logger
        )

    @provide(scope=Scope.APP)
    async def get_auth_api(
        self,
        config: Config,
        redis_client: redis.Redis,
        logger: logging.Logger
    ) -> AuthAPI:
        return AuthAPI(
            secret_key=config.jwt.secret_key,
            redis_client=redis_client,
            logger=logger
        )

    @provide(scope=Scope.APP)
    async def get_contact_api(
            self,
            auth_api: AuthAPI,
            redis_client: redis.Redis,
            logger: logging.Logger
    ) -> ContactAPI:
        return ContactAPI(
            auth_api=auth_api,
            redis_client=redis_client,
            logger=logger
        )

    @provide(scope=Scope.APP)
    async def get_message_api(
            self,
            auth_api: AuthAPI,
            redis_client: redis.Redis,
            logger: logging.Logger,
    ) -> MessageAPI:
        return MessageAPI(
            auth_api=auth_api,
            redis_client=redis_client,
            logger=logger,
        )
