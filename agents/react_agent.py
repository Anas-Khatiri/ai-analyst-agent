"""LLM-driven ReAct alternative to agents/ml_analyst_agent.py's deterministic
skill selection, per ADR-004-react-skill-selection.md.

Only the investigative-skill *selection* mechanism changes here: instead of
SkillSelectionEngine's alert_triggers metadata matching, a google-adk Agent
reads each investigative skill's prose `description`, reasons about which is
relevant to the incident, calls it (Action), observes the resulting Finding,
and loops (ADK's Runner implements the Thought -> Action -> Observation
multi-turn loop internally once tools are attached to the agent -- this
module does not hand-roll that loop, it consumes and logs the Event stream
the Runner produces).

Everything downstream of selection is identical to the deterministic agent:
the terminal wave (root_cause_prioritization -> incident_summary) and report
assembly reuse `execute_wave`/`record_selection`/`assemble_report`/`intake`
from agents/ml_analyst_agent.py unchanged. Combination stays deterministic
regardless of how a skill was selected, per .agents/CONTEXT.md §6.3.

Terminal skills are never exposed to the LLM as tools: their required_inputs
include `dict[str, Finding]`, which an LLM cannot meaningfully construct.

Investigative tools take no LLM-supplied arguments. Their connection
parameters come from the same `skill_parameters` trigger field the
deterministic agent uses (Phase 3-5 scoped limitation — see
agents/ml_analyst_agent.py's module docstring) and are bound into the tool
closure ahead of time, so the LLM's only decision is *whether* a tool is
relevant, never fabricating dataset identifiers it has no way to know.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from agents.ml_analyst_agent import (
    InvestigationSession,
    assemble_report,
    execute_wave,
    intake,
    record_selection,
)
from agents.skill_selection_engine import SkillSelectionEngine
from shared.logging_utils import log_event
from shared.schemas.incident import (
    IncidentReport,
    IncidentSignature,
    RawTrigger,
    SkillSelectionRecord,
)
from shared.skill_loader import execute_skill
from shared.skill_registry import SkillMetadata, SkillRegistry

_LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
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


def make_investigative_tool_function(
    meta: SkillMetadata,
    script_path: Path,
    resolved_params: dict[str, object],
    session: InvestigationSession,
) -> Callable[[], Awaitable[dict[str, object]]]:
    """Builds a zero-argument async tool function for one investigative skill.

    `__name__`/`__doc__` are set from the skill's metadata so
    `google.adk.tools.FunctionTool` derives the tool's name and description
    from them — this is the literal "reading skill descriptions in prose"
    mechanism the LLM reasons over.
    """

    async def tool() -> dict[str, object]:
        log_event(
            _LOGGER,
            logging.INFO,
            __name__,
            session.incident_id,
            "skill_invocation_requested",
            skill_name=meta.name,
        )
        try:
            # Any exception here means "unavailable"; never crash the ReAct loop.
            finding = await execute_skill(meta, script_path, resolved_params)
        except Exception as exc:
            session.unavailable_skills[meta.name] = str(exc)
            log_event(
                _LOGGER,
                logging.WARNING,
                __name__,
                session.incident_id,
                "skill_unavailable",
                skill_name=meta.name,
                error=str(exc),
            )
            return {"error": str(exc)}

        session.findings[meta.name] = finding
        session.executed_skills.add(meta.name)
        session.ledger.add_finding(meta.name, finding, wave_index=0)
        session.selection_records.append(
            SkillSelectionRecord(skill_name=meta.name, trigger_reason="llm_selected", wave_index=0)
        )
        log_event(
            _LOGGER,
            logging.INFO,
            __name__,
            session.incident_id,
            "skill_invocation_observed",
            skill_name=meta.name,
            confidence_score=finding.confidence_score,
        )
        return finding.model_dump(mode="json")

    tool.__name__ = meta.name
    tool.__doc__ = meta.description
    return tool


def build_investigative_tools(
    registry: SkillRegistry,
    skill_parameters: dict[str, dict[str, object]],
    session: InvestigationSession,
) -> list[FunctionTool]:
    """One FunctionTool per registered investigative skill. Terminal skills
    (role != "investigative") are never included — see module docstring."""
    tools: list[FunctionTool] = []
    for meta in registry.registry.values():
        if meta.role != "investigative":
            continue
        script_path = registry.resolve_script_path(meta)
        resolved_params = skill_parameters.get(meta.name, {})
        func = make_investigative_tool_function(meta, script_path, resolved_params, session)
        tools.append(FunctionTool(func))
    return tools


def _log_react_event(event: Event, session: InvestigationSession) -> int:
    """Logs each Thought (text)/Action (function_call)/Observation
    (function_response) part of one ADK Event. Returns the number of tool
    calls seen in this event, for the caller's safety-cap bookkeeping."""
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
            log_event(
                _LOGGER,
                logging.INFO,
                __name__,
                session.incident_id,
                "react_observation",
                tool_name=part.function_response.name,
            )
    return tool_calls_seen


async def _run_react_loop(
    signature: IncidentSignature,
    tools: list[FunctionTool],
    session: InvestigationSession,
    model: str,
    max_tool_calls: int,
) -> None:
    agent = Agent(name=APP_NAME, model=model, instruction=_INSTRUCTION, tools=tools)
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
    """The ReAct alternative to agents/ml_analyst_agent.py::analyze_incident.

    Requires a working GEMINI_API_KEY (loaded from .env if not already in
    the environment) — this path makes real LLM calls, unlike the
    deterministic agent.
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

    tools = build_investigative_tools(registry, raw.skill_parameters, session)
    if tools:
        await _run_react_loop(signature, tools, session, model, max_tool_calls)

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
