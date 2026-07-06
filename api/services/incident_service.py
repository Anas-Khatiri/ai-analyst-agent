"""Service layer between the /incidents route and the ReAct agent.

Thin by design: validation already happened at the router (the request body
is parsed as api.schemas.incidents.IncidentRequest), and everything about
skill selection, MCP invocation, and report assembly lives in
agents/react_agent.py -- this module's only job is adapting that
entrypoint's dict-based contract to/from typed objects, enforcing a request
timeout, and translating failures into typed exceptions the router can map
to clean HTTP responses instead of leaking a raw traceback to the client.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from agents.react_agent import analyze_incident_react
from api.config import APISettings
from api.schemas.incidents import IncidentRequest, IncidentResponse
from shared.logging_utils import log_event

_LOGGER = logging.getLogger(__name__)


class IncidentAnalysisError(RuntimeError):
    """The agent raised while investigating the incident."""


class IncidentAnalysisTimeout(RuntimeError):
    """The agent did not finish within the configured request timeout."""


async def run_incident_analysis(
    trigger: IncidentRequest,
    *,
    model: str | None,
    max_tool_calls: int | None,
    settings: APISettings,
) -> IncidentResponse:
    request_id = str(uuid4())
    resolved_model = model or settings.default_model
    resolved_max_tool_calls = max_tool_calls or settings.default_max_tool_calls

    log_event(
        _LOGGER,
        logging.INFO,
        __name__,
        request_id,
        "incident_analysis_requested",
        alert_type=trigger.alert_type,
        model=resolved_model,
        max_tool_calls=resolved_max_tool_calls,
    )

    try:
        report = await asyncio.wait_for(
            analyze_incident_react(
                trigger.model_dump(mode="json"),
                model=resolved_model,
                max_tool_calls=resolved_max_tool_calls,
            ),
            timeout=settings.request_timeout_seconds,
        )
    except TimeoutError as exc:
        log_event(
            _LOGGER,
            logging.ERROR,
            __name__,
            request_id,
            "incident_analysis_timeout",
            timeout_seconds=settings.request_timeout_seconds,
        )
        raise IncidentAnalysisTimeout(
            f"Incident analysis exceeded {settings.request_timeout_seconds}s"
        ) from exc
    except Exception as exc:
        log_event(
            _LOGGER,
            logging.ERROR,
            __name__,
            request_id,
            "incident_analysis_failed",
            error=str(exc),
        )
        raise IncidentAnalysisError("Incident analysis failed") from exc

    log_event(
        _LOGGER,
        logging.INFO,
        __name__,
        request_id,
        "incident_analysis_completed",
        incident_id=report.incident_id,
        confidence_score=report.confidence_score,
    )
    return report
