import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka
import uvicorn

from src.config import Config
from src.providers import AppProvider
from src.adapters.api.routers import AuthAPI, ContactAPI, MessageAPI

def setup_logging(logging_level: str):
    level_mapping = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL,
    }

    level = level_mapping.get(logging_level.upper(), logging.INFO)

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        force=True,
    )

    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured with level: {logging_level}")

@asynccontextmanager
async def lifespan(app: FastAPI):

    config = await _container.get(Config)

    setup_logging(config.logging_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting application initialization...")

    auth_api = await _container.get(AuthAPI)
    contact_api = await _container.get(ContactAPI)
    message_api = await _container.get(MessageAPI)

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(auth_api.get_router())
    app.include_router(contact_api.get_router())
    app.include_router(message_api.get_router())

    asyncio.create_task(message_api.start_redis_listener())

    logger.info("Application initialized successfully")

    yield

    if _container:
        await _container.close()

_container = make_async_container(AppProvider())
app = FastAPI(
    title="Apata API",
    version="1.0.0",
    lifespan=lifespan
)
setup_dishka(_container, app)

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
