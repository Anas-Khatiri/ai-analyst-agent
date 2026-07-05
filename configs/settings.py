# configs/settings.py
"""Application configuration settings.

This module defines AppSettings which loads configuration values from
environment variables and an optional .env file using Pydantic's
BaseSettings. The class is deliberately small - only the variables that
are required by the current project are listed. Additional settings can be
added later without changing existing code.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Centralised configuration for the ML-Analyst agent.

    The fields correspond to environment variables. By default values are
    empty strings so that a missing variable raises a validation error at
    runtime, ensuring the application fails fast when required configuration
    is not provided.
    """

    GEMINI_API_KEY: str = ""
    GOOGLE_GENAI_USE_ENTERPRISE: str = "FALSE"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    def __repr__(self) -> str:
        return (
            f"AppSettings(GEMINI_API_KEY=******, "
            f"GOOGLE_GENAI_USE_ENTERPRISE={self.GOOGLE_GENAI_USE_ENTERPRISE})"
        )


settings = AppSettings()
