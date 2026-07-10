"""The ML Analyst Agent's sole entrypoint: an LLM-driven ReAct agent that
dynamically selects investigative skills and invokes them through a real
MCP (Model Context Protocol) tool call, per
ADR-004-react-skill-selection.md, ADR-005-mcp-skill-invocation.md,
ADR-006-remove-deterministic-mode.md, and ADR-007-skill-selection-gate.md.

A google-adk `Agent` reads each investigative skill's prose `description`,
reasons about which is relevant to the incident, calls it (Action), observes
the resulting Finding, and loops (ADK's Runner implements the Thought ->
Action -> Observation multi-turn loop internally once tools are attached to
the agent -- this module does not hand-roll that loop, it consumes and logs
the Event stream the Runner produces).

Per ADR-007-skill-selection-gate.md, that ReAct loop only ever sees the
subset of investigative skills `agents/planning/skill_selector.py::SkillSelector`
already judged relevant to this incident from metadata alone (never an MCP
tool definition) -- see `analyze_incident_react` below for how the two
stages compose.

Everything downstream of selection reuses `execute_wave`/`record_selection`/
`assemble_report`/`intake` from agents/workflow/investigation_core.py unchanged: the
terminal wave (root_cause_prioritization -> incident_summary) and report
assembly. Combination stays deterministic regardless of how a skill was
selected, per .agents/CONTEXT.md §6.3.

Terminal skills are never exposed to the LLM as tools: their required_inputs
include `dict[str, Finding]`, which an LLM cannot meaningfully construct.

Investigative skills are invoked through a real MCP (Model Context Protocol)
tool call, per ADR-005-mcp-skill-invocation.md: a fresh
services/mcp/skill_mcp_server.py subprocess is spawned per incident, and this
module connects to it as an MCP client via google-adk's `McpToolset`. The
incident's `skill_parameters` (Phase 3-5 scoped limitation — see
agents/workflow/investigation_core.py's module docstring) are passed to the server via
an environment variable at subprocess launch, *before* any tool schema is
ever shown to the LLM — every tool the server advertises is genuinely
zero-argument, so the LLM's only decision is *whether* a tool is relevant,
never fabricating dataset identifiers it has no way to know. Because skill
execution now happens in a separate process, the InvestigationSession
bookkeeping that used to happen inside the (in-process) tool closure instead
happens here, client-side, off each MCP tool call's `function_response`
event -- see `_extract_tool_payload`/`_record_tool_observation` below.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

from agents.planning.skill_selection_engine import SkillSelectionEngine
from agents.planning.skill_selector import SkillSelector
from agents.workflow.investigation_core import (
    InvestigationSession,
    assemble_report,
    execute_wave,
    intake,
    record_selection,
)
from domain.finding import Finding
from domain.incident import (
    IncidentReport,
    IncidentSignature,
    RawTrigger,
    SkillSelectionRecord,
)
from infra.logging_utils import log_event
from infra.skill_registry import SkillRegistry

_LOGGER = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MODEL = "gemini-3.5-flash"
MAX_TOOL_CALLS = 6
APP_NAME = "ml_analyst_react"
USER_ID = "ml_analyst_agent"

_INSTRUCTION = (
    "You are the investigative reasoning step of an ML Analyst Agent "
    "(Pipeline Sentinel), a production ML incident root-cause-analysis system.\n\n"
    "You have access to diagnostic tools. Each tool's description states what "
    "it investigates; it needs no arguments from you -- call it by name and it "
    "will use its own pre-configured connection details for this incident.\n\n"
    "Think step by step about which tool(s) are relevant to the incident "
    "described in the next message, call the ones you judge useful to gather "
    "evidence, and read each tool's result before deciding whether to "
    "investigate further. Do not call a tool whose description does not match "
    "this incident. Once you have gathered sufficient evidence -- or if none "
    "of the available tools seem relevant -- stop calling tools and reply "
    "with a short plain-text summary of what you investigated and why."
)


def _build_initial_message(signature: IncidentSignature) -> str:
    return (
        f"Incident alert_type={signature.alert_type!r}, "
        f"affected_system={signature.affected_system.identifier!r} "
        f"({signature.affected_system.system_type}), "
        f"severity={signature.severity!r}."
    )


def build_skill_mcp_toolset(
    skill_parameters: dict[str, dict[str, object]],
    selected_skill_names: set[str] | None = None,
) -> McpToolset:
    """Builds the MCP client toolset for one incident investigation.

    Spawns services/mcp/skill_mcp_server.py as a fresh stdio subprocess,
    passing the incident's resolved `skill_parameters` via an environment
    variable read once at server startup — see module docstring for why this
    keeps every advertised tool genuinely zero-argument.

    `selected_skill_names`, per ADR-007-skill-selection-gate.md, restricts
    which investigative skills the spawned server even registers as MCP
    tools: `None` exposes every investigative skill (pre-ADR-007 behavior);
    a concrete set (including empty) is passed through as-is so only that
    subset is ever visible to the ReAct loop's LLM.
    """
    env = {**os.environ, "SKILL_PARAMETERS_JSON": json.dumps(skill_parameters)}
    if selected_skill_names is not None:
        env["SELECTED_SKILLS_JSON"] = json.dumps(sorted(selected_skill_names))
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=["-m", "services.mcp.skill_mcp_server"],
                cwd=str(_REPO_ROOT),
                env=env,
            ),
            timeout=10.0,
        )
    )


def _extract_tool_payload(mcp_response: dict[str, object]) -> dict[str, object]:
    """Normalizes an MCP tool call's response dict (an ADK `MCPTool`'s
    `run_async` result, itself a `mcp.types.CallToolResult.model_dump()`)
    back to the flat `{"error": ...}` | Finding-shaped dict every
    investigative tool returned in-process before MCP (ADR-005 §3.2).

    `structuredContent` is the primary path: services/mcp/skill_mcp_server.py
    never raises, so a skill failure surfaces there as `{"error": ...}`, not
    as `isError: true` — the `isError` branch below only covers an MCP
    protocol-level failure (e.g. the server process itself misbehaving).
    """
    if mcp_response.get("isError"):
        content = mcp_response.get("content")
        first = content[0] if isinstance(content, list) and content else None
        text = first.get("text") if isinstance(first, dict) else None
        return {"error": text or "MCP tool call reported isError=true with no content."}
    structured = mcp_response.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = mcp_response.get("content")
    first = content[0] if isinstance(content, list) and content else None
    if isinstance(first, dict) and isinstance(first.get("text"), str):
        parsed = json.loads(first["text"])
        if isinstance(parsed, dict):
            return parsed
    return mcp_response


def _record_tool_observation(
    tool_name: str, payload: dict[str, object], session: InvestigationSession
) -> None:
    """Client-side counterpart of the old in-closure session mutation: called
    once per MCP tool call, off that call's `function_response` payload."""
    if "error" in payload:
        error_message = str(payload["error"])
        session.unavailable_skills[tool_name] = error_message
        session.selection_records.append(
            SkillSelectionRecord(
                skill_name=tool_name,
                trigger_reason="llm_selected",
                wave_index=0,
                excluded=True,
                exclusion_reason=error_message,
            )
        )
        log_event(
            _LOGGER,
            logging.WARNING,
            __name__,
            session.incident_id,
            "skill_unavailable",
            skill_name=tool_name,
            error=error_message,
        )
        return

    finding = Finding.model_validate(payload)
    session.findings[tool_name] = finding
    session.executed_skills.add(tool_name)
    session.ledger.add_finding(tool_name, finding, wave_index=0)
    session.selection_records.append(
        SkillSelectionRecord(skill_name=tool_name, trigger_reason="llm_selected", wave_index=0)
    )
    log_event(
        _LOGGER,
        logging.INFO,
        __name__,
        session.incident_id,
        "skill_invocation_observed",
        skill_name=tool_name,
        confidence_score=finding.confidence_score,
    )


def _log_react_event(event: Event, session: InvestigationSession) -> int:
    """Logs each Thought (text)/Action (function_call)/Observation
    (function_response) part of one ADK Event, and — for each Observation —
    records the MCP tool call's result into `session` (see
    `_record_tool_observation`). Returns the number of tool calls seen in
    this event, for the caller's safety-cap bookkeeping."""
    tool_calls_seen = 0
    if event.content is None or event.content.parts is None:
        return tool_calls_seen

    for part in event.content.parts:
        if part.text:
            log_event(
                _LOGGER,
                logging.INFO,
                __name__,
                session.incident_id,
                "react_thought",
                text=part.text,
            )
        if part.function_call is not None:
            tool_calls_seen += 1
            log_event(
                _LOGGER,
                logging.INFO,
                __name__,
                session.incident_id,
                "react_action",
                tool_name=part.function_call.name,
            )
        if part.function_response is not None:
            tool_name = part.function_response.name
            log_event(
                _LOGGER,
                logging.INFO,
                __name__,
                session.incident_id,
                "react_observation",
                tool_name=tool_name,
            )
            if tool_name is not None:
                payload = _extract_tool_payload(dict(part.function_response.response or {}))
                _record_tool_observation(tool_name, payload, session)
    return tool_calls_seen


async def _run_react_loop(
    signature: IncidentSignature,
    toolset: McpToolset,
    session: InvestigationSession,
    model: str,
    max_tool_calls: int,
) -> None:
    agent = Agent(name=APP_NAME, model=model, instruction=_INSTRUCTION, tools=[toolset])
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=signature.incident_id
    )
    message = types.Content(role="user", parts=[types.Part(text=_build_initial_message(signature))])

    tool_call_count = 0
    async for event in runner.run_async(
        user_id=USER_ID, session_id=signature.incident_id, new_message=message
    ):
        tool_call_count += _log_react_event(event, session)
        if tool_call_count >= max_tool_calls:
            log_event(
                _LOGGER,
                logging.WARNING,
                __name__,
                session.incident_id,
                "react_tool_call_cap_reached",
                max_tool_calls=max_tool_calls,
            )
            break


async def analyze_incident_react(
    trigger: dict[str, object],
    model: str = DEFAULT_MODEL,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> IncidentReport:
    """The ML Analyst Agent's single public entrypoint.

    Requires a working GEMINI_API_KEY (loaded from .env if not already in
    the environment) — this path makes real LLM calls and spawns a real MCP
    server subprocess per incident.
    """
    load_dotenv()
    raw = RawTrigger.model_validate(trigger)
    signature = intake(raw)
    session = InvestigationSession(signature.incident_id)
    registry = SkillRegistry()
    registry.scan_skills()

    log_event(
        _LOGGER,
        logging.INFO,
        __name__,
        session.incident_id,
        "incident_received",
        alert_type=signature.alert_type,
        mode="react",
    )

    selector = SkillSelector(registry, model)
    selection_result = await selector.select(signature, raw.skill_parameters)
    session.selection_records.extend(selection_result.records)

    if selection_result.selected_skill_names:
        toolset = build_skill_mcp_toolset(
            raw.skill_parameters, set(selection_result.selected_skill_names)
        )
        try:
            await _run_react_loop(signature, toolset, session, model, max_tool_calls)
        finally:
            await toolset.close()

    engine = SkillSelectionEngine(registry)
    terminal_plan = engine.select_next_wave(
        wave_id=1, skill_parameters=raw.skill_parameters, already_executed=session.executed_skills
    )
    record_selection(terminal_plan, session)
    if terminal_plan.selected_skills:
        await execute_wave(terminal_plan, registry, session, signature)

    log_event(
        _LOGGER,
        logging.INFO,
        __name__,
        session.incident_id,
        "investigation_complete",
        executed_skills=sorted(session.executed_skills),
        unavailable_skills=sorted(session.unavailable_skills),
    )
    return assemble_report(signature, session, terminal_plan)
