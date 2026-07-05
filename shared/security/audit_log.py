import json
import logging
from datetime import UTC, datetime

from .redaction import redact_text


def audit_event(
    logger: logging.Logger,
    level: int,
    module: str,
    session_id: str,
    message: str,
    **extra: object,
) -> None:
    """Emit a structured audit log line with PII redacted.

    All string values in ``extra`` are passed through :func:`redact_text` to
    ensure that email addresses, API keys, passwords, etc. never appear in logs.
    """

    def _is_secret_key(key: str) -> bool:
        return any(s in key.lower() for s in ("api_key", "token", "secret"))

    redacted_extra = {
        k: "[REDACTED]"
        if isinstance(v, str) and _is_secret_key(k)
        else redact_text(v)
        if isinstance(v, str)
        else v
        for k, v in extra.items()
    }
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": logging.getLevelName(level),
        "module": module,
        "session_id": session_id,
        "message": redact_text(message),
        **redacted_extra,
    }
    logger.log(level, json.dumps(payload, default=str))
