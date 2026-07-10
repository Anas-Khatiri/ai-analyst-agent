"""API-layer configuration.

Scoped to the FastAPI application only — not a project-wide settings module
(the earlier `configs/settings.py` was removed as dead weight; this one is
actually wired into `api/routers/incidents.py` via `get_settings`).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    """Defaults for the /incidents endpoint. Overridable via .env or
    environment variables (e.g. `DEFAULT_MODEL`, `REQUEST_TIMEOUT_SECONDS`)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    default_model: str = "gemini-3.5-flash"
    default_max_tool_calls: int = 6
    request_timeout_seconds: float = 60.0

    api_key: str = Field(
        default="",
        description=(
            "Required to call POST /incidents (sent as the X-API-Key header). "
            "Empty means auth is not configured -- requests are rejected, not "
            "silently allowed through, until an operator sets this explicitly."
        ),
    )


@lru_cache
def get_settings() -> APISettings:
    return APISettings()
