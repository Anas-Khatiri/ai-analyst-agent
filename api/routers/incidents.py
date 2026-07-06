"""POST /incidents: the ReAct/MCP agent's HTTP entrypoint.

Synchronous by design (see docs/api/incidents_endpoint.md): a real
investigation makes a live Gemini call and spawns a real MCP server
subprocess (agents/react_agent.py), so a single request can take on the
order of 8-20 seconds. The request body is validated as
api.schemas.incidents.IncidentRequest before the agent ever runs -- a
malformed body never reaches the agent.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.config import APISettings, get_settings
from api.schemas.incidents import IncidentRequest, IncidentResponse
from api.services.incident_service import (
    IncidentAnalysisError,
    IncidentAnalysisTimeout,
    run_incident_analysis,
)

router = APIRouter(tags=["incidents"])


@router.post("/incidents", response_model=IncidentResponse, status_code=200)
async def create_incident(
    trigger: IncidentRequest,
    model: str | None = Query(
        default=None, description="Overrides the default Gemini model for this request."
    ),
    max_tool_calls: int | None = Query(
        default=None, description="Overrides the default investigative tool-call cap."
    ),
    settings: APISettings = Depends(get_settings),
) -> IncidentResponse:
    """Submits an incident for investigation and returns the completed
    IncidentReport once the agent finishes."""
    try:
        return await run_incident_analysis(
            trigger, model=model, max_tool_calls=max_tool_calls, settings=settings
        )
    except IncidentAnalysisTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except IncidentAnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
