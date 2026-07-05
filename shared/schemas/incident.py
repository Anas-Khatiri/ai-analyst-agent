from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.finding import ActionItem, Finding, HypothesisCandidate

Severity = Literal["low", "medium", "high", "critical"]
SystemType = Literal[
    "model_serving",
    "feature_pipeline",
    "training_pipeline",
    "deployment",
    "evaluation",
    "infrastructure",
]
TriggerReason = Literal[
    "signal_match", "evidence_triggered", "fallback", "terminal", "llm_selected"
]
"""`llm_selected` per ADR-004-react-skill-selection.md: a skill an LLM ReAct
loop chose to invoke by reasoning over its prose `description`, as opposed
to the deterministic `alert_triggers` match `signal_match` represents."""


class AffectedSystem(BaseModel):
    """Per incident_schema.md §3.3."""

    model_config = ConfigDict(extra="forbid")

    system_type: SystemType
    identifier: str
    environment: str = "production"


class RawTrigger(BaseModel):
    """Per incident_schema.md §2 — the practical input to Incident Intake.

    The full doc splits Raw Trigger (arbitrary upstream format) from
    Incident Signature (normalized) to defend against a genuinely messy
    upstream alerting integration. No such integration exists yet in this
    phase, so this model folds in the structured fields Intake needs
    directly (`severity`, `affected_system`, `detected_at`) rather than
    burying them in an opaque `raw_payload`, while still keeping
    `raw_payload` for anything else the caller wants to pass through.
    """

    model_config = ConfigDict(extra="forbid")

    alert_type: str
    severity: Severity = "medium"
    affected_system: AffectedSystem
    detected_at: datetime
    source_system: str = "unknown"
    raw_payload: dict[str, object] = Field(default_factory=dict)
    skill_parameters: dict[str, dict[str, object]] = Field(
        default_factory=dict,
        description=(
            "Phase 3-5 scoped limitation: concrete kwargs per skill name, supplied "
            "by whoever raises the incident, since no real feature-store/context "
            "resolution exists yet to derive these automatically. See "
            "agents/ml_analyst_agent.py module docstring."
        ),
    )


class ContextMetadata(BaseModel):
    """Per incident_schema.md §3.4. Not exercised by the current 4-skill catalog."""

    model_config = ConfigDict(extra="forbid")

    recent_deployments: list[dict[str, object]] = Field(default_factory=list)
    concurrent_alerts: list[str] = Field(default_factory=list)
    model_metadata: dict[str, object] | None = None


class IncidentSignature(BaseModel):
    """Per incident_schema.md §3 — the immutable, normalized object every
    downstream component (Skill Selection Engine, skills) reasons over."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    alert_type: str
    severity: Severity
    affected_system: AffectedSystem
    detected_at: datetime
    context_metadata: ContextMetadata = Field(default_factory=ContextMetadata)
    raw_trigger_ref: str


class SkillSelectionRecord(BaseModel):
    """Per skill_selection_engine.md §3.6 — the published form of a Selection Plan wave entry."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str
    trigger_reason: TriggerReason
    wave_index: int
    excluded: bool = False
    exclusion_reason: str | None = None


class IncidentReport(BaseModel):
    """Per incident_schema.md §4.

    `findings` is `dict[str, Finding]` here (skill_name -> Finding) rather
    than the doc's literal `list[Finding]` — a bare list loses the skill
    association every consumer of this object actually needs, and every
    skill entrypoint in this codebase already expects `dict[str, Finding]`
    for the same reason.
    """

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    schema_version: str = "1.0.0"
    incident_summary: str
    observed_symptoms: list[str] = Field(default_factory=list)
    selected_skills: list[SkillSelectionRecord] = Field(default_factory=list)
    findings: dict[str, Finding] = Field(default_factory=dict)
    root_cause_ranking: list[HypothesisCandidate] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    partial_investigation: bool = False
    requires_human_review: bool = False
    recommended_actions: list[ActionItem] = Field(default_factory=list)
    preventive_actions: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    published_at: datetime
