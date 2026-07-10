from __future__ import annotations

from datetime import datetime

import _incident_summary_core as core
from pydantic import BaseModel, ConfigDict

from domain.finding import Finding

DEFAULT_ROOT_CAUSE_SKILL_NAME = "root_cause_prioritization"


class IncidentSummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    alert_type: str
    affected_system: str
    detected_at: datetime
    findings: dict[str, Finding]
    root_cause_skill_name: str = DEFAULT_ROOT_CAUSE_SKILL_NAME


async def run(**params: object) -> Finding:
    """Entrypoint contract per DYNAMIC_DISCOVERY_DESIGN.md §3.3: a module-level `run()`.

    Like root_cause_prioritization, this terminal skill performs no external
    data access — it is a pure, deterministic compilation over the Finding
    objects already produced earlier in the investigation. The compiled
    Markdown post-mortem is carried in `investigation_summary`; the Finding
    contract has no dedicated field for it (skill_contract.md §5 is fixed
    and forbids extra fields), and that narrative field is the one place a
    long-form report legitimately belongs.
    """
    validated = IncidentSummaryInput.model_validate(params)

    result = core.run_incident_summary(
        incident_id=validated.incident_id,
        alert_type=validated.alert_type,
        affected_system=validated.affected_system,
        detected_at=validated.detected_at,
        findings=validated.findings,
        root_cause_skill_name=validated.root_cause_skill_name,
    )

    root_cause_finding = validated.findings.get(validated.root_cause_skill_name)
    possible_root_causes = (
        list(root_cause_finding.possible_root_causes) if root_cause_finding is not None else []
    )

    return Finding(
        investigation_summary=result.incident_report_md,
        evidence=result.cited_evidence,
        possible_root_causes=possible_root_causes,
        confidence_score=result.confidence_score,
        recommended_actions=result.remediation_actions,
        preventive_actions=result.preventive_actions,
        limitations=result.limitations,
    )
