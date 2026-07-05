"""ML Analyst Agent core orchestrator.

Ties together the Skill Registry, Skill Selection Engine, and the dynamic
Skill Loader into the pipeline specified in docs/agents/ml_analyst_agent.md:
Incident Intake -> Skill Selector -> Skill Executor -> Evidence Aggregator,
looping wave by wave until the Selection Engine signals termination, then
the terminal wave (whichever skills are registered with a terminal role,
today root_cause_prioritization then incident_summary).

This module never imports a skill module by name. Every skill is resolved
generically through the SkillRegistry (parsed from each SKILL.md's YAML
frontmatter) and invoked through shared/skill_loader.py — adding a fifth
skill to skills/ requires zero changes here, per ADR-001-dynamic-skills.md.

Scope: deterministic orchestration only (ml_analyst_agent.md §13 names
"Deterministic Orchestration" as a core design principle). No google-adk/
Gemini LLM reasoning loop is wired in here, and no FastAPI layer.

See agents/react_agent.py for an LLM-driven ReAct alternative that swaps
only the investigative-skill-selection mechanism for LLM reasoning over
each skill's prose description — it reuses `execute_wave`/`record_selection`/
`assemble_report`/`intake` from this module unchanged for everything
downstream of selection (per ADR-004-react-skill-selection.md), since
combination must stay deterministic (.agents/CONTEXT.md §6.3) regardless
of how a skill was selected.

Phase 3-5 scoped limitation: the caller must supply `skill_parameters` in
the trigger (skill name -> concrete kwargs), since no real feature-store/
context-resolution infrastructure exists yet to derive these automatically
from the incident signature alone. A skill whose required inputs aren't
supplied here is excluded at Stage 2 (skill_selection_engine.md §3.2), not
crashed on.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from agents.skill_selection_engine import SelectionPlan, SkillSelectionEngine
from shared.logging_utils import log_event
from shared.schemas.evidence_ledger import EvidenceLedger
from shared.schemas.finding import ActionItem, Finding, HypothesisCandidate
from shared.schemas.incident import (
    ContextMetadata,
    IncidentReport,
    IncidentSignature,
    RawTrigger,
    SkillSelectionRecord,
)
from shared.skill_loader import execute_skill
from shared.skill_registry import SkillRegistry

_LOGGER = logging.getLogger(__name__)

LOW_CONFIDENCE_THRESHOLD = 0.5
HIGH_CONFIDENCE_THRESHOLD = 0.8
MAX_WAVES = 8

_UNCLASSIFIED_REASONS = {"no_skill_matched", "registry_unavailable"}


class InvestigationSession:
    """Mutable state for a single analyze_incident() call: which skills have
    run, their Findings, and the Evidence Ledger.

    Purely in-memory for this phase — SYSTEM_ARCHITECTURE.md's Dual-Store
    Session Service (Redis/Postgres persistence) is out of scope here; this
    is a synchronous, single-call investigation, not a persisted or
    resumable one.
    """

    def __init__(self, incident_id: str) -> None:
        self.incident_id = incident_id
        self.findings: dict[str, Finding] = {}
        self.executed_skills: set[str] = set()
        self.unavailable_skills: dict[str, str] = {}
        self.selection_records: list[SkillSelectionRecord] = []
        self.ledger = EvidenceLedger(incident_id=incident_id)


def intake(trigger: RawTrigger) -> IncidentSignature:
    incident_id = str(uuid.uuid4())
    return IncidentSignature(
        incident_id=incident_id,
        alert_type=trigger.alert_type,
        severity=trigger.severity,
        affected_system=trigger.affected_system,
        detected_at=trigger.detected_at,
        context_metadata=ContextMetadata(),
        raw_trigger_ref=f"trigger:{incident_id}",
    )


def _resolve_params(
    selected_skill_name: str,
    resolved_params: dict[str, object],
    registry: SkillRegistry,
    session: InvestigationSession,
    signature: IncidentSignature,
) -> dict[str, object]:
    meta = registry.get(selected_skill_name)
    params: dict[str, object] = dict(resolved_params)
    if meta is not None and meta.role != "investigative":
        params["findings"] = dict(session.findings)
    if meta is not None and meta.role == "terminal_reporting":
        params.setdefault("incident_id", session.incident_id)
        params.setdefault("alert_type", signature.alert_type)
        params.setdefault("affected_system", signature.affected_system.identifier)
        params.setdefault("detected_at", signature.detected_at)
    return params


async def execute_wave(
    plan: SelectionPlan,
    registry: SkillRegistry,
    session: InvestigationSession,
    signature: IncidentSignature,
) -> None:
    """Runs every skill in `plan`, in list order (§5.4: a wave's list order is
    itself the sequencing for a `sequential` wave; a `parallel` wave's
    members are independent, so in-order execution is equally correct,
    just not concurrent — a straightforward future optimization).

    A skill that raises or returns something malformed is marked
    unavailable (ml_analyst_agent.md §11) and the rest of the wave
    continues; a skill failure never aborts the whole investigation.
    """
    for selected in plan.selected_skills:
        meta = registry.get(selected.skill_name)
        if meta is None:
            session.unavailable_skills[selected.skill_name] = "not found in registry"
            continue

        params = _resolve_params(
            selected.skill_name, selected.resolved_params, registry, session, signature
        )
        script_path = registry.resolve_script_path(meta)

        log_event(
            _LOGGER,
            logging.INFO,
            __name__,
            session.incident_id,
            "skill_execution_started",
            skill_name=meta.name,
            wave_id=plan.wave_id,
        )
        try:
            # Any exception here means "unavailable" (§11); never abort the wave.
            finding = await execute_skill(meta, script_path, params)
        except Exception as exc:
            session.unavailable_skills[meta.name] = str(exc)
            log_event(
                _LOGGER,
                logging.WARNING,
                __name__,
                session.incident_id,
                "skill_unavailable",
                skill_name=meta.name,
                wave_id=plan.wave_id,
                error=str(exc),
            )
            continue

        session.findings[meta.name] = finding
        session.executed_skills.add(meta.name)
        session.ledger.add_finding(meta.name, finding, plan.wave_id)
        log_event(
            _LOGGER,
            logging.INFO,
            __name__,
            session.incident_id,
            "skill_execution_completed",
            skill_name=meta.name,
            wave_id=plan.wave_id,
            confidence_score=finding.confidence_score,
        )


def record_selection(plan: SelectionPlan, session: InvestigationSession) -> None:
    for excluded in plan.excluded_candidates:
        session.selection_records.append(
            SkillSelectionRecord(
                skill_name=excluded.skill_name,
                trigger_reason="signal_match",
                wave_index=plan.wave_id,
                excluded=True,
                exclusion_reason=excluded.reason,
            )
        )
    for selected in plan.selected_skills:
        session.selection_records.append(
            SkillSelectionRecord(
                skill_name=selected.skill_name,
                trigger_reason=selected.trigger_reason,
                wave_index=plan.wave_id,
            )
        )


async def analyze_incident(trigger: dict[str, object]) -> IncidentReport:
    """The ML Analyst Agent's single public entrypoint, per SYSTEM_SPEC.md §5."""
    raw = RawTrigger.model_validate(trigger)
    signature = intake(raw)
    session = InvestigationSession(signature.incident_id)
    registry = SkillRegistry()
    registry.scan_skills()
    engine = SkillSelectionEngine(registry)

    log_event(
        _LOGGER,
        logging.INFO,
        __name__,
        session.incident_id,
        "incident_received",
        alert_type=signature.alert_type,
    )

    plan = engine.select_initial_wave(signature, raw.skill_parameters)
    wave_id = 0
    while True:
        record_selection(plan, session)

        if plan.selected_skills:
            await execute_wave(plan, registry, session, signature)

        if plan.continuation_signal == "terminate":
            break

        wave_id += 1
        if wave_id > MAX_WAVES:
            break
        plan = engine.select_next_wave(wave_id, raw.skill_parameters, session.executed_skills)

    log_event(
        _LOGGER,
        logging.INFO,
        __name__,
        session.incident_id,
        "investigation_complete",
        executed_skills=sorted(session.executed_skills),
        unavailable_skills=sorted(session.unavailable_skills),
    )
    return assemble_report(signature, session, plan)


def assemble_report(
    signature: IncidentSignature, session: InvestigationSession, final_plan: SelectionPlan
) -> IncidentReport:
    root_cause_finding = session.findings.get("root_cause_prioritization")
    reporting_finding = session.findings.get("incident_summary")
    unclassified = final_plan.termination_reason in _UNCLASSIFIED_REASONS
    partial = bool(session.unavailable_skills)

    root_cause_ranking: list[HypothesisCandidate] = []
    recommended_actions: list[ActionItem] = []
    preventive_actions: list[str] = []

    if root_cause_finding is None:
        confidence_score = 0.0
        if unclassified:
            summary = (
                f"Incident {signature.incident_id}: no investigative skill matched alert "
                f"type '{signature.alert_type}'; escalated for human review."
            )
        else:
            summary = (
                f"Incident {signature.incident_id}: root cause could not be determined "
                "(ranking step unavailable); escalated for human review."
            )
    else:
        confidence_score = root_cause_finding.confidence_score
        root_cause_ranking = root_cause_finding.possible_root_causes
        recommended_actions = root_cause_finding.recommended_actions
        preventive_actions = root_cause_finding.preventive_actions
        summary = (
            reporting_finding.investigation_summary
            if reporting_finding is not None
            else root_cause_finding.investigation_summary
        )

    requires_human_review = (
        unclassified or root_cause_finding is None or confidence_score < LOW_CONFIDENCE_THRESHOLD
    )

    return IncidentReport(
        incident_id=signature.incident_id,
        incident_summary=summary,
        observed_symptoms=[signature.alert_type],
        selected_skills=session.selection_records,
        findings=session.findings,
        root_cause_ranking=root_cause_ranking,
        confidence_score=confidence_score,
        partial_investigation=partial,
        requires_human_review=requires_human_review,
        recommended_actions=recommended_actions,
        preventive_actions=preventive_actions,
        supporting_evidence=[entry.entry_id for entry in session.ledger.entries],
        published_at=datetime.now(UTC),
    )
