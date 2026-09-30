import logging
import os
from collections.abc import AsyncIterator

import redis.asyncio as redis
from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.adapters.database.dao.chat import ChatDAO
from src.adapters.database.dao.common import CommonDAO
from src.adapters.database.dao.contact import ContactDAO
from src.adapters.database.dao.file import FileDAO
from src.adapters.database.dao.message import MessageDAO
from src.adapters.database.dao.user import UserDAO
from src.adapters.database.service import (
    ChatService,
    ContactService,
    FileService,
    MessageService,
    UserService,
)
from src.adapters.encryption.dao.ed import EDDAO
from src.adapters.encryption.dao.jwt import JWTDAO
from src.adapters.encryption.service.ed import EDService
from src.adapters.encryption.service.jwt import JWTService
from src.adapters.realtime import (
    RealtimeConnectionManager,
    RealtimePublisher,
    RealtimeSubscriber,
)
from src.application.routers.chat import ChatAPI
from src.application.routers.contact import ContactAPI
from src.application.routers.file import FileAPI
from src.application.routers.message import MessageAPI
from src.application.routers.realtime import RealtimeAPI
from src.application.routers.user import AuthAPI
from src.application.services import RealtimePresenceService


class AppProvider(Provider):
    scope = Scope.APP

    @provide(scope=Scope.APP)
    def logger(self) -> logging.Logger:
        return logging.getLogger("apata-router")

    @provide(scope=Scope.APP)
    async def database_engine(self) -> AsyncIterator[AsyncEngine]:
        engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide(scope=Scope.APP)
    def session_factory(
        self, database_engine: AsyncEngine
    ) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(database_engine, expire_on_commit=False)

    @provide(scope=Scope.REQUEST)
    async def database_session(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    def common_dao(self, database_session: AsyncSession) -> CommonDAO:
        return CommonDAO(database_session)

    @provide(scope=Scope.REQUEST)
    def chat_dao(self, database_session: AsyncSession) -> ChatDAO:
        return ChatDAO(database_session)

    @provide(scope=Scope.REQUEST)
    def user_dao(self, database_session: AsyncSession) -> UserDAO:
        return UserDAO(database_session)

    @provide(scope=Scope.REQUEST)
    def contact_dao(self, database_session: AsyncSession) -> ContactDAO:
        return ContactDAO(database_session)

    @provide(scope=Scope.REQUEST)
    def message_dao(self, database_session: AsyncSession) -> MessageDAO:
        return MessageDAO(database_session)

    @provide(scope=Scope.REQUEST)
    def file_dao(self, database_session: AsyncSession) -> FileDAO:
        return FileDAO(database_session)

    @provide(scope=Scope.REQUEST)
    def user_service(self, user_dao: UserDAO, common_dao: CommonDAO) -> UserService:
        return UserService(user_dao=user_dao, common_dao=common_dao)

    @provide(scope=Scope.REQUEST)
    def contact_service(
        self, contact_dao: ContactDAO, common_dao: CommonDAO
    ) -> ContactService:
        return ContactService(contact_dao=contact_dao, common_dao=common_dao)

    @provide(scope=Scope.REQUEST)
    def chat_service(
        self,
        chat_dao: ChatDAO,
        user_dao: UserDAO,
        common_dao: CommonDAO,
    ) -> ChatService:
        return ChatService(
            chat_dao=chat_dao,
            user_dao=user_dao,
            common_dao=common_dao,
        )

    @provide(scope=Scope.REQUEST)
    def message_service(
        self,
        message_dao: MessageDAO,
        chat_dao: ChatDAO,
        contact_dao: ContactDAO,
        common_dao: CommonDAO,
    ) -> MessageService:
        return MessageService(
            message_dao=message_dao,
            chat_dao=chat_dao,
            contact_dao=contact_dao,
            common_dao=common_dao,
        )

    @provide(scope=Scope.REQUEST)
    def file_service(
        self,
        file_dao: FileDAO,
        chat_dao: ChatDAO,
        user_dao: UserDAO,
        common_dao: CommonDAO,
    ) -> FileService:
        return FileService(
            file_dao=file_dao,
            chat_dao=chat_dao,
            user_dao=user_dao,
            common_dao=common_dao,
        )

    @provide(scope=Scope.APP)
    async def redis_client(self) -> AsyncIterator[redis.Redis]:
        client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        try:
            yield client
        finally:
            await client.aclose()

    @provide(scope=Scope.APP)
    def realtime_connection_manager(
        self,
        logger: logging.Logger,
    ) -> RealtimeConnectionManager:
        return RealtimeConnectionManager(logger)

    @provide(scope=Scope.APP)
    def realtime_publisher(
        self,
        redis_client: redis.Redis,
        logger: logging.Logger,
    ) -> RealtimePublisher:
        return RealtimePublisher(redis_client, logger)

    @provide(scope=Scope.APP)
    def realtime_presence_service(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: logging.Logger,
    ) -> RealtimePresenceService:
        return RealtimePresenceService(session_factory, logger)

    @provide(scope=Scope.APP)
    def realtime_subscriber(
        self,
        redis_client: redis.Redis,
        realtime_connection_manager: RealtimeConnectionManager,
        logger: logging.Logger,
    ) -> RealtimeSubscriber:
        return RealtimeSubscriber(
            redis_client,
            realtime_connection_manager,
            logger,
        )

    @provide(scope=Scope.APP)
    def auth_api(self) -> AuthAPI:
        return AuthAPI()

    @provide(scope=Scope.APP)
    def contact_api(self) -> ContactAPI:
        return ContactAPI()

    @provide(scope=Scope.APP)
    def chat_api(self) -> ChatAPI:
        return ChatAPI()

    @provide(scope=Scope.APP)
    def message_api(self) -> MessageAPI:
        return MessageAPI()

    @provide(scope=Scope.APP)
    def file_api(self) -> FileAPI:
        return FileAPI()

    @provide(scope=Scope.APP)
    def realtime_api(self) -> RealtimeAPI:
        return RealtimeAPI()

    @provide(scope=Scope.APP)
    def ed_dao(self) -> EDDAO:
        return EDDAO()

    @provide(scope=Scope.APP)
    def ed_service(self, ed_dao: EDDAO) -> EDService:
        return EDService(ed_dao=ed_dao)

    @provide(scope=Scope.APP)
    def jwt_dao(self) -> JWTDAO:
        return JWTDAO(
            algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
            access_token_expire_minutes=int(
                os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "480")
            ),
            secret_key=os.environ["JWT_SECRET_KEY"],
        )

    @provide(scope=Scope.APP)
    def jwt_service(self, jwt_dao: JWTDAO) -> JWTService:
        return JWTService(jwt_dao=jwt_dao)
