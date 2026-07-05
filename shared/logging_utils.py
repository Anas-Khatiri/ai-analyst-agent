from __future__ import annotations

import json
import logging
from datetime import UTC, datetime


def log_event(
    logger: logging.Logger,
    level: int,
    module: str,
    session_id: str,
    message: str,
    **extra: object,
) -> None:
    """Emits one JSON-structured log line per .agents/CONTEXT.md §3
    (timestamp, level, module, session_id, plus event-specific fields)."""
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": logging.getLevelName(level),
        "module": module,
        "session_id": session_id,
        "message": message,
        **extra,
    }
    logger.log(level, json.dumps(payload, default=str))
