from dataclasses import dataclass
from environs import Env
from typing import Optional

@dataclass
class JWTConfig:
    secret_key: str

@dataclass
class DBConfig:
    host: str | None = None
    port: int | None = None
    name: str | None = None
    user: str | None = None
    password: str | None = None

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

@dataclass
class RedisConfig:
    host: str | None = 'localhost'
    port: int | None = 6379

@dataclass
class Config:
    """ Config """
    logging_level: str
    jwt: JWTConfig
    db: DBConfig
    redis: RedisConfig

def load_config(path: str | None) -> Config:
    env = Env()
    env.read_env(path)

    return Config(
        logging_level=env('LOGGING_LEVEL', 'INFO'),
        jwt=JWTConfig(
            secret_key=env('SECRET_KEY'),
        ),
        db=DBConfig(
            host=env('DB_HOST', None),
            port=env.int('DB_PORT', None),
            name=env('DB_NAME', None),
            user=env('DB_USER', None),
            password=env('DB_PASSWORD', None),
        ),
        redis=RedisConfig(
            host=env('REDIS_HOST', 'localhost'),
            port=env.int('REDIS_PORT', 6379)
        )
    )
