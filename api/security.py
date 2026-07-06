"""Basic API-key auth for routes that need it.

Deliberately simple -- one static key, one header, checked with a
constant-time comparison. Health/liveness endpoints (api/main.py) do not use
this: platform health probes (e.g. Railway) need to reach those without a
secret. Only routes that actually do agent work (POST /incidents) require it.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from api.config import APISettings, get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    provided_key: str | None = Security(_api_key_header),
    settings: APISettings = Depends(get_settings),
) -> None:
    """Raises 401/503 on failure; returns None (no value needed) on success.

    Fails closed: an unconfigured API key rejects every request rather than
    silently allowing them through -- forgetting to set API_KEY must not
    quietly leave the endpoint open.
    """
    if not settings.api_key:
        raise HTTPException(
            status_code=503,
            detail="API key auth is not configured on this server (API_KEY is unset).",
        )
    if provided_key is None or not secrets.compare_digest(provided_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header.")
