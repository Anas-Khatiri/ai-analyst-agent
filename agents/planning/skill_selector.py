"""Pre-ReAct skill selection, per ADR-007-skill-selection-gate.md.

`agents/reasoning/react_agent.py` used to spawn `services/mcp/skill_mcp_server.py`
with every investigative skill registered as an MCP tool, regardless of
whether it had anything to do with the incident at hand -- fine with two
skills, but a cost that scales with catalog size rather than with incident
relevance as the plugin catalog (ADR-001-dynamic-skills.md) grows.

This module runs first and narrows that down: a lightweight, metadata-only
LLM call that reads each investigative skill's SkillMetadata (name,
description, role, required input names, alert_triggers) plus the
incident's signature, and decides which skills are worth trying. It never
sees an MCP tool definition and never sees resolved skill_parameters
*values* (e.g. real dataset IDs) -- only the parameter *names* a skill
declares it needs. Only `SkillSelector.select`'s resulting
`selected_skill_names` get exposed as MCP tools to the ReAct loop
(agents/reasoning/react_agent.py::build_skill_mcp_toolset).

Mirrors the restraint agents/planning/skill_selection_engine.py already observes
(§1.3 of that module's docstring intent): this class never invokes a skill
itself, only decides which the caller's ReAct loop should be allowed to
consider.
"""

from __future__ import annotations

import logging

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from domain.incident import IncidentSignature, SkillSelectionRecord
from infra.logging_utils import log_event
from infra.skill_registry import SkillMetadata, SkillRegistry, missing_required_inputs

_LOGGER = logging.getLogger(__name__)

APP_NAME = "ml_analyst_skill_selector"
USER_ID = "ml_analyst_agent"

_INSTRUCTION = (
    "You are the skill-selection step of an ML Analyst Agent (Pipeline "
    "Sentinel), a production ML incident root-cause-analysis system.\n\n"
    "Below is the incident and a catalog of diagnostic skills, each "
    "described by name, a prose description of what it investigates, and "
    "the alert types it is tagged as relevant to. You do not run these "
    "skills yourself -- you only decide which ones are plausibly relevant "
    "to this incident, so that only those are made available to the next "
    "reasoning step.\n\n"
    "Select every skill that could plausibly help diagnose this incident. "
    "Do not select a skill whose description clearly does not match. If "
    "none apply, return an empty list -- that is a valid, honest answer."
)


class SkillSelectionDecision(BaseModel):
    """Structured output contract for the selection LLM call -- the model
    replies with exactly this shape, no free text, no tool calls.

    Deliberately does *not* set `extra="forbid"` (unlike every other schema
    in this codebase, per .agents/CONTEXT.md §2.1): Pydantic renders
    `extra="forbid"` as `additionalProperties: false` in the JSON schema,
    which Gemini's structured-output `response_schema` field does not
    support and rejects with a 400 (`Unknown name "additional_properties"`)
    -- this model is only ever used as an ADK `output_schema`, never as a
    tool-input schema, so the §2.1 rule's rationale (validate untrusted
    tool arguments strictly) doesn't apply to it the same way.
    """

    selected_skills: list[str] = Field(default_factory=list)
    rationale: str


class SkillSelectionResult(BaseModel):
    """What `SkillSelector.select` returns: the registry-validated
    selection, plus a full audit trail (including every excluded
    candidate and why) suitable for merging straight into
    InvestigationSession.selection_records."""

    model_config = ConfigDict(extra="forbid")

    selected_skill_names: list[str] = Field(default_factory=list)
    records: list[SkillSelectionRecord] = Field(default_factory=list)


def _format_catalog_entry(meta: SkillMetadata) -> str:
    required = ", ".join(sorted(meta.required_inputs)) or "none"
    tags = ", ".join(meta.alert_triggers) or "none"
    return (
        f"- name: {meta.name}\n"
        f"  description: {meta.description}\n"
        f"  role: {meta.role}\n"
        f"  required_inputs: {required}\n"
        f"  tags: {tags}"
    )


def _build_selection_prompt(signature: IncidentSignature, candidates: list[SkillMetadata]) -> str:
    catalog = "\n".join(_format_catalog_entry(meta) for meta in candidates)
    return (
        f"Incident alert_type={signature.alert_type!r}, "
        f"affected_system={signature.affected_system.identifier!r} "
        f"({signature.affected_system.system_type}), "
        f"severity={signature.severity!r}.\n\n"
        f"Available skills:\n{catalog}"
    )


class SkillSelector:
    """Runs the pre-ReAct skill-selection step. Depends only on
    SkillRegistry (dependency inversion: this class never imports the MCP
    server or a skill module directly).

    Reuses the same `model` already threaded through
    `analyze_incident_react(model=...)` for simplicity -- a distinct,
    cheaper model for this lighter-weight call is a reasonable future
    swap, since `model` is already an independent constructor argument.
    """

    def __init__(self, registry: SkillRegistry, model: str) -> None:
        self._registry = registry
        self._model = model

    async def select(
        self,
        signature: IncidentSignature,
        skill_parameters: dict[str, dict[str, object]],
    ) -> SkillSelectionResult:
        candidates = self._registry.investigative_skills()
        runnable, records = _filter_runnable(candidates, skill_parameters)

        if not runnable:
            log_event(
                _LOGGER,
                logging.INFO,
                __name__,
                signature.incident_id,
                "skill_selection_skipped_no_runnable_candidates",
            )
            return SkillSelectionResult(selected_skill_names=[], records=records)

        decision = await self._run_selection_llm(signature, runnable)

        runnable_names = {meta.name for meta in runnable}
        # Registry-validated intersection: a hallucinated or unknown name
        # is silently dropped, never trusted as-is.
        selected_names = [name for name in decision.selected_skills if name in runnable_names]

        for meta in runnable:
            if meta.name in selected_names:
                continue
            records.append(
                SkillSelectionRecord(
                    skill_name=meta.name,
                    trigger_reason="llm_selected",
                    wave_index=0,
                    excluded=True,
                    exclusion_reason="not selected by skill-selection step",
                )
            )

        return SkillSelectionResult(selected_skill_names=selected_names, records=records)

    async def _run_selection_llm(
        self, signature: IncidentSignature, candidates: list[SkillMetadata]
    ) -> SkillSelectionDecision:
        agent = Agent(
            name=APP_NAME,
            model=self._model,
            instruction=_INSTRUCTION,
            output_schema=SkillSelectionDecision,
        )
        runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
        await runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=signature.incident_id
        )
        message = types.Content(
            role="user",
            parts=[types.Part(text=_build_selection_prompt(signature, candidates))],
        )

        decision = SkillSelectionDecision(selected_skills=[], rationale="")
        async for event in runner.run_async(
            user_id=USER_ID, session_id=signature.incident_id, new_message=message
        ):
            if not event.is_final_response():
                continue
            if event.content is None or event.content.parts is None:
                continue
            text = "".join(
                part.text for part in event.content.parts if part.text and not part.thought
            )
            if text:
                decision = SkillSelectionDecision.model_validate_json(text)

        log_event(
            _LOGGER,
            logging.INFO,
            __name__,
            signature.incident_id,
            "skill_selection_decided",
            selected_skills=decision.selected_skills,
            rationale=decision.rationale,
        )
        return decision


def _filter_runnable(
    candidates: list[SkillMetadata], skill_parameters: dict[str, dict[str, object]]
) -> tuple[list[SkillMetadata], list[SkillSelectionRecord]]:
    """Deterministically excludes any skill that could never successfully
    run regardless of relevance -- required parameters weren't supplied in
    the trigger. Not LLM judgment (.agents/CONTEXT.md §6.3): a skill that
    structurally cannot execute is never shown to the model at all."""
    runnable: list[SkillMetadata] = []
    records: list[SkillSelectionRecord] = []
    for meta in candidates:
        missing = missing_required_inputs(meta, skill_parameters)
        if missing:
            records.append(
                SkillSelectionRecord(
                    skill_name=meta.name,
                    trigger_reason="llm_selected",
                    wave_index=0,
                    excluded=True,
                    exclusion_reason=f"required input(s) not supplied: {', '.join(missing)}",
                )
            )
            continue
        runnable.append(meta)
    return runnable, records
