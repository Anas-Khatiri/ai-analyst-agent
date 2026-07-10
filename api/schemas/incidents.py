"""API-facing request/response schemas for /incidents.

Both shapes already exist in domain/incident.py as the ReAct agent's
own validated input/output contract (agents/reasoning/react_agent.py::analyze_incident_react)
-- re-exported here under API-facing names so routers import from
api.schemas, never reaching into domain.incident directly, without
duplicating a second source of truth for the same shape.
"""

from __future__ import annotations

from domain.incident import IncidentReport, RawTrigger

IncidentRequest = RawTrigger
IncidentResponse = IncidentReport

__all__ = ["IncidentRequest", "IncidentResponse"]
