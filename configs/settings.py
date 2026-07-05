from __future__ import annotations

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(8000, env="PORT")
    redis_host: str = Field("localhost", env="REDIS_HOST")
    redis_port: int = Field(6379, env="REDIS_PORT")
    database_url: PostgresDsn | None = Field(default=None, env="DATABASE_URL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def redis_dsn(self) -> RedisDsn:
        """Construct a Redis DSN from host and port."""
        return RedisDsn.build(scheme="redis", host=self.redis_host, port=self.redis_port)


# Export a singleton for convenience
settings = AppSettings()
