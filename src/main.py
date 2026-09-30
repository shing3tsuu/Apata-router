import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI, Request, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.adapters.realtime import RealtimeSubscriber
from src.application.routers.chat import ChatAPI
from src.application.routers.contact import ContactAPI
from src.application.routers.file import FileAPI
from src.application.routers.message import MessageAPI
from src.application.routers.realtime import RealtimeAPI
from src.application.routers.user import AuthAPI
from src.providers import AppProvider


def setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )


def rate_limit_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RateLimitExceeded)
    return _rate_limit_exceeded_handler(request, exc)


_container = make_async_container(AppProvider())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    logger = logging.getLogger("apata-router")

    auth_api = await _container.get(AuthAPI)
    chat_api = await _container.get(ChatAPI)
    contact_api = await _container.get(ContactAPI)
    file_api = await _container.get(FileAPI)
    message_api = await _container.get(MessageAPI)
    realtime_api = await _container.get(RealtimeAPI)
    realtime_subscriber = await _container.get(RealtimeSubscriber)
    app.state.limiter = auth_api.get_limiter()
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
    app.include_router(auth_api.get_router())
    app.include_router(chat_api.get_router())
    app.include_router(contact_api.get_router())
    app.include_router(file_api.get_router())
    app.include_router(message_api.get_router())
    app.include_router(realtime_api.get_router())
    await realtime_subscriber.start()
    logger.info("Application initialized")

    try:
        yield
    finally:
        await realtime_subscriber.stop()
        await _container.close()


app = FastAPI(title="Apata Router API", version="0.1.0", lifespan=lifespan)
setup_dishka(_container, app)


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000)
