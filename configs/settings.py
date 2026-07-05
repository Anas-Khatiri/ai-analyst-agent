from __future__ import annotations

from pydantic import ConfigDict, Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    host: str = Field(default="0.0.0.0", json_schema_extra={"env": "HOST"})
    port: int = Field(default=8000, json_schema_extra={"env": "PORT"})
    redis_host: str = Field(default="localhost", json_schema_extra={"env": "REDIS_HOST"})
    redis_port: int = Field(default=6379, json_schema_extra={"env": "REDIS_PORT"})
    database_url: PostgresDsn | None = Field(
        default=None, json_schema_extra={"env": "DATABASE_URL"}
    )

    model_config = ConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    def redis_dsn(self) -> RedisDsn:
        """Construct a Redis DSN from host and port."""
        return RedisDsn.build(scheme="redis", host=self.redis_host, port=self.redis_port)


# Export a singleton for convenience
settings = AppSettings()
