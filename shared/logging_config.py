from __future__ import annotations

import sys

import structlog
from structlog.processors import JSONRenderer, TimeStamper


def configure_logging() -> None:
    """Configure structlog to emit JSON logs to stdout.

    This function is intended to be called once at application start‑up.
    It sets a global logger configuration that other modules can obtain via
    ``structlog.get_logger()``.
    """
    structlog.configure(
        processors=[
            TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        wrapper_class=structlog.make_filtering_bound_logger(0),
        cache_logger_on_first_use=True,
    )
