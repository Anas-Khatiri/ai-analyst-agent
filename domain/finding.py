from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RiskTier = Literal["auto_executable", "requires_approval"]
TimeHorizon = Literal["immediate", "medium_term"]


class TimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime


class EvidenceItem(BaseModel):
    """A single, individually-citable data point. Shape per skill_contract.md §5.1."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(
        description="Skill-local identifier for this entry, referenced by "
        "HypothesisCandidate.supporting_evidence/conflicting_evidence and "
        "ActionItem.justifying_finding_refs within the same Finding."
    )
    subject: str = Field(description="The concrete thing being measured.")
    metric: str = Field(description="The statistic computed.")
    value: float = Field(description="The observed value.")
    baseline: float | None = Field(default=None, description="The reference/expected value.")
    time_window: TimeWindow
    source_skill: str = Field(
        description="The emitting skill's name, filled automatically by the executor."
    )


class HypothesisCandidate(BaseModel):
    """A skill-local candidate root cause. Shape per skill_contract.md §5.2."""

    model_config = ConfigDict(extra="forbid")

    cause: str = Field(description="A specific, falsifiable causal statement.")
    supporting_evidence: list[str] = Field(default_factory=list)
    conflicting_evidence: list[str] = Field(default_factory=list)
    local_confidence: float = Field(ge=0.0, le=1.0)


class ActionItem(BaseModel):
    """Shape per incident_schema.md §4.3."""

    model_config = ConfigDict(extra="forbid")

    description: str
    risk_tier: RiskTier
    justifying_finding_refs: list[str] = Field(default_factory=list)
    time_horizon: TimeHorizon


class Finding(BaseModel):
    """The fixed output shape every skill returns. Shape per skill_contract.md §5."""

    model_config = ConfigDict(extra="forbid")

    investigation_summary: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    possible_root_causes: list[HypothesisCandidate] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    recommended_actions: list[ActionItem] = Field(default_factory=list)
    preventive_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
