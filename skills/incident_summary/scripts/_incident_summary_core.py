from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.finding import ActionItem, EvidenceItem, Finding

ConfidenceBand = Literal["high", "medium", "low"]

HIGH_CONFIDENCE_THRESHOLD = 0.8
MEDIUM_CONFIDENCE_THRESHOLD = 0.5
OWN_PREVENTIVE_RECOMMENDATION = (
    "Include this post-mortem in quarterly operational reviews to track "
    "recurring system weaknesses."
)

_SECTION_LABELS: dict[str, str] = {
    "executive_summary": "Executive Summary",
    "observed_symptoms": "Observed Symptoms",
    "root_cause_analysis": "Root Cause Analysis",
    "evidence_citations": "Evidence Citations",
    "remediation_actions": "Remediation Actions",
    "preventive_recommendations": "Preventive Recommendations",
}


class IncidentReportSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str
    observed_symptoms: str
    root_cause_analysis: str
    evidence_citations: str
    remediation_actions: str
    preventive_recommendations: str


class IncidentSummaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_report_md: str
    sections: IncidentReportSections
    cited_evidence: list[EvidenceItem] = Field(default_factory=list)
    remediation_actions: list[ActionItem] = Field(default_factory=list)
    preventive_actions: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    limitations: list[str] = Field(default_factory=list)


def compute_confidence(root_cause_finding: Finding | None) -> tuple[float, ConfidenceBand]:
    if root_cause_finding is None or not root_cause_finding.possible_root_causes:
        return 0.3, "low"
    if root_cause_finding.confidence_score >= HIGH_CONFIDENCE_THRESHOLD:
        return 0.92, "high"
    if root_cause_finding.confidence_score >= MEDIUM_CONFIDENCE_THRESHOLD:
        return 0.65, "medium"
    return 0.3, "low"


def resolve_cited_evidence(
    root_cause_finding: Finding | None, findings: dict[str, Finding]
) -> list[EvidenceItem]:
    """Resolves qualified 'skill_name::evidence_id' refs from the ranked hypotheses
    back to their original EvidenceItem in each contributing skill's own Finding.

    Unresolvable or unqualified references (e.g. this skill's own synthetic
    'skill_name::evidence_id' convention not being followed) are skipped rather
    than fabricated.
    """
    if root_cause_finding is None:
        return []

    cited: list[EvidenceItem] = []
    seen_refs: set[str] = set()
    for hypothesis in root_cause_finding.possible_root_causes:
        for ref in hypothesis.supporting_evidence:
            if ref in seen_refs or "::" not in ref:
                continue
            seen_refs.add(ref)
            skill_name, evidence_id = ref.split("::", 1)
            source_finding = findings.get(skill_name)
            if source_finding is None:
                continue
            for item in source_finding.evidence:
                if item.evidence_id == evidence_id:
                    cited.append(item)
                    break
    return cited


def build_executive_summary(root_cause_finding: Finding | None, incident_id: str) -> str:
    if root_cause_finding is None or not root_cause_finding.possible_root_causes:
        return (
            f"Incident {incident_id}: root cause could not be determined from available findings."
        )
    top = root_cause_finding.possible_root_causes[0]
    return (
        f"Incident {incident_id} was most likely caused by **{top.cause}** "
        f"(confidence: {top.local_confidence:.0%})."
    )


def build_observed_symptoms(alert_type: str, affected_system: str, detected_at: datetime) -> str:
    return (
        f"- Alert Type: {alert_type}\n"
        f"- Affected System: {affected_system}\n"
        f"- Detected At: {detected_at.isoformat()}"
    )


def build_root_cause_analysis(root_cause_finding: Finding | None) -> str:
    if root_cause_finding is None or not root_cause_finding.possible_root_causes:
        return ""
    lines = []
    for index, hypothesis in enumerate(root_cause_finding.possible_root_causes, start=1):
        confidence_pct = f"{hypothesis.local_confidence:.0%}"
        lines.append(f"{index}. **{hypothesis.cause}** — confidence: {confidence_pct}")
        if hypothesis.conflicting_evidence:
            conflicting = ", ".join(hypothesis.conflicting_evidence)
            lines.append(f"   - Conflicting evidence: {conflicting}")
    return "\n".join(lines)


def _format_delta(value: float, baseline: float | None) -> str:
    if baseline is None:
        return "—"
    delta = value - baseline
    arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
    return f"{arrow} {delta:+.4f}"


def _format_row(item: EvidenceItem) -> str:
    baseline_str = f"{item.baseline:.4f}" if item.baseline is not None else "n/a"
    delta_str = _format_delta(item.value, item.baseline)
    return (
        f"| {item.source_skill} | {item.subject} | {item.metric} "
        f"| {item.value:.4f} | {baseline_str} | {delta_str} |"
    )


def build_evidence_citations_markdown(cited_evidence: list[EvidenceItem]) -> str:
    if not cited_evidence:
        return ""
    header = "| Skill | Subject | Metric | Observed | Baseline | Delta |\n"
    separator = "|---|---|---|---|---|---|\n"
    rows = "\n".join(_format_row(item) for item in cited_evidence)
    return header + separator + rows


def build_remediation_actions(root_cause_finding: Finding | None) -> list[ActionItem]:
    if root_cause_finding is None:
        return []
    return list(root_cause_finding.recommended_actions)


_TIME_HORIZON_LABELS: dict[str, str] = {"immediate": "Immediate", "medium_term": "Medium-term"}
_RISK_TIER_LABELS: dict[str, str] = {
    "auto_executable": "auto-executable",
    "requires_approval": "requires approval",
}


def build_remediation_actions_markdown(actions: list[ActionItem]) -> str:
    if not actions:
        return ""
    blocks: list[str] = []
    for horizon_key, horizon_label in _TIME_HORIZON_LABELS.items():
        horizon_actions = [a for a in actions if a.time_horizon == horizon_key]
        if not horizon_actions:
            continue
        lines = [f"### {horizon_label}"]
        for action in horizon_actions:
            risk_label = _RISK_TIER_LABELS.get(action.risk_tier, action.risk_tier)
            lines.append(f"- {action.description} *({risk_label})*")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_preventive_actions(findings: dict[str, Finding]) -> list[str]:
    seen: list[str] = []
    for finding in findings.values():
        for action in finding.preventive_actions:
            if action not in seen:
                seen.append(action)
    if OWN_PREVENTIVE_RECOMMENDATION not in seen:
        seen.append(OWN_PREVENTIVE_RECOMMENDATION)
    return seen


_EMPTY_SECTION_PLACEHOLDERS: dict[str, str] = {
    "root_cause_analysis": "_No root cause could be determined from available findings._",
    "evidence_citations": "_No evidence was available to cite._",
    "remediation_actions": "_No remediation actions were recommended._",
    "preventive_recommendations": "_None._",
}


def render_report_markdown(
    incident_id: str,
    sections: IncidentReportSections,
    confidence_score: float,
    confidence_band: ConfidenceBand,
) -> str:
    def _section(field_name: str, label: str) -> str:
        content = getattr(sections, field_name).strip()
        if not content:
            content = _EMPTY_SECTION_PLACEHOLDERS.get(field_name, "_None._")
        return f"## {label}\n\n{content}"

    body = "\n\n".join(_section(field_name, label) for field_name, label in _SECTION_LABELS.items())
    return (
        f"# Incident Report: {incident_id}\n\n"
        f"**Confidence:** {confidence_score:.0%} ({confidence_band})\n\n"
        "---\n\n"
        f"{body}\n"
    )


def validate_sections(sections: IncidentReportSections) -> list[str]:
    return [
        f"Section '{label}' could not be populated from available findings."
        for field_name, label in _SECTION_LABELS.items()
        if not getattr(sections, field_name).strip()
    ]


def run_incident_summary(
    incident_id: str,
    alert_type: str,
    affected_system: str,
    detected_at: datetime,
    findings: dict[str, Finding],
    root_cause_skill_name: str = "root_cause_prioritization",
) -> IncidentSummaryResult:
    root_cause_finding = findings.get(root_cause_skill_name)

    limitations: list[str] = []
    for skill_name, finding in findings.items():
        limitations.extend(f"[{skill_name}] {limitation}" for limitation in finding.limitations)
    if root_cause_finding is None:
        limitations.append(
            f"'{root_cause_skill_name}' finding was not supplied; root cause is undetermined."
        )

    cited_evidence = resolve_cited_evidence(root_cause_finding, findings)
    remediation_actions = build_remediation_actions(root_cause_finding)
    preventive_actions = build_preventive_actions(findings)

    sections = IncidentReportSections(
        executive_summary=build_executive_summary(root_cause_finding, incident_id),
        observed_symptoms=build_observed_symptoms(alert_type, affected_system, detected_at),
        root_cause_analysis=build_root_cause_analysis(root_cause_finding),
        evidence_citations=build_evidence_citations_markdown(cited_evidence),
        remediation_actions=build_remediation_actions_markdown(remediation_actions),
        preventive_recommendations="\n".join(f"- {item}" for item in preventive_actions),
    )
    limitations.extend(validate_sections(sections))

    confidence_score, confidence_band = compute_confidence(root_cause_finding)

    return IncidentSummaryResult(
        incident_report_md=render_report_markdown(
            incident_id, sections, confidence_score, confidence_band
        ),
        sections=sections,
        cited_evidence=cited_evidence,
        remediation_actions=remediation_actions,
        preventive_actions=preventive_actions,
        confidence_score=confidence_score,
        confidence_band=confidence_band,
        limitations=limitations,
    )
