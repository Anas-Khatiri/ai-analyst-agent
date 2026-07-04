from __future__ import annotations

from datetime import UTC, datetime

import _root_cause_prioritization_core as core
from pydantic import BaseModel, ConfigDict

from shared.schemas.finding import (
    ActionItem,
    EvidenceItem,
    Finding,
    HypothesisCandidate,
    TimeWindow,
)

SKILL_NAME = "root_cause_prioritization"


class RootCausePrioritizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: dict[str, Finding]


def _qualify(ref: core.EvidenceRef) -> str:
    return f"{ref.skill_name}::{ref.evidence_id}"


def _build_evidence(result: core.RankingResult, window: TimeWindow) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    for index, hypothesis in enumerate(result.ranked_hypotheses):
        evidence.append(
            EvidenceItem(
                evidence_id=f"rank_hypothesis_{index}",
                subject=f"hypothesis_{index}",
                metric="rank_score",
                value=hypothesis.score,
                baseline=None,
                time_window=window,
                source_skill=SKILL_NAME,
            )
        )
    return evidence


def _build_hypotheses(result: core.RankingResult) -> list[HypothesisCandidate]:
    return [
        HypothesisCandidate(
            cause=hypothesis.cause,
            supporting_evidence=[_qualify(ref) for ref in hypothesis.supporting_evidence],
            conflicting_evidence=[_qualify(ref) for ref in hypothesis.conflicting_evidence],
            local_confidence=hypothesis.score,
        )
        for hypothesis in result.ranked_hypotheses
    ]


def _select_actions(
    top: core.MergedHypothesis | None, findings: dict[str, Finding]
) -> list[ActionItem]:
    if top is None:
        return []

    evidence_ids_by_skill: dict[str, set[str]] = {}
    for ref in top.supporting_evidence:
        evidence_ids_by_skill.setdefault(ref.skill_name, set()).add(ref.evidence_id)

    selected: list[ActionItem] = []
    for skill_name, evidence_ids in evidence_ids_by_skill.items():
        finding = findings.get(skill_name)
        if finding is None:
            continue
        for action in finding.recommended_actions:
            if set(action.justifying_finding_refs) & evidence_ids:
                selected.append(action)
    return selected


def _collect_preventive_actions(findings: dict[str, Finding]) -> list[str]:
    seen: list[str] = []
    for finding in findings.values():
        for action in finding.preventive_actions:
            if action not in seen:
                seen.append(action)
    return seen


async def run(**params: object) -> Finding:
    """Entrypoint contract per DYNAMIC_DISCOVERY_DESIGN.md §3.3: a module-level `run()`.

    Unlike investigative skills, this terminal skill performs no external data
    access — it is a pure, deterministic combination over the Finding objects
    already produced by other skills in this investigation (per
    .agents/CONTEXT.md §6.3 and root_cause_analysis.md).
    """
    validated = RootCausePrioritizationInput.model_validate(params)

    result = core.run_root_cause_prioritization(validated.findings)

    now = datetime.now(UTC)
    window = TimeWindow(start=now, end=now)
    top = result.ranked_hypotheses[0] if result.ranked_hypotheses else None

    summary = (
        f"Ranked {len(result.ranked_hypotheses)} candidate root cause(s) from "
        f"{len(validated.findings)} skill finding(s). "
        + (
            f"Primary trigger: {top.cause}"
            if top is not None
            else "No credible hypothesis survived ranking."
        )
    )

    return Finding(
        investigation_summary=summary,
        evidence=_build_evidence(result, window),
        possible_root_causes=_build_hypotheses(result),
        confidence_score=result.confidence_score,
        recommended_actions=_select_actions(top, validated.findings),
        preventive_actions=_collect_preventive_actions(validated.findings),
        limitations=result.limitations,
    )
