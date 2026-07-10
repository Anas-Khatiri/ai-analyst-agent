from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domain.evidence_ledger import fingerprint as compute_fingerprint
from domain.finding import EvidenceItem, Finding

ConfidenceBand = Literal["high", "medium", "low"]

CORROBORATION_BONUS_PER_SKILL = 0.05
CONFLICT_PENALTY_PER_ITEM = 0.1
NOISE_FLOOR = 0.2
HIGH_MARGIN_THRESHOLD = 0.15
MEDIUM_MARGIN_THRESHOLD = 0.05
HIGH_SCORE_THRESHOLD = 0.8
MEDIUM_SCORE_THRESHOLD = 0.5


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_name: str
    evidence_id: str


class MergedHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cause: str
    contributing_skills: list[str] = Field(default_factory=list)
    supporting_evidence: list[EvidenceRef] = Field(default_factory=list)
    conflicting_evidence: list[EvidenceRef] = Field(default_factory=list)
    local_confidences: list[float] = Field(default_factory=list)
    fingerprints: list[str] = Field(
        default_factory=list,
        description=(
            "Simplified evidence_model.md §3 fingerprints (subject::metric, "
            "normalized) resolved from supporting_evidence — the basis for "
            "cross-skill corroboration matching, independent of any skill's "
            "own local evidence_id naming."
        ),
    )
    score: float = Field(ge=0.0, le=1.0, default=0.0)


class RankingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ranked_hypotheses: list[MergedHypothesis] = Field(default_factory=list)
    dropped_below_noise_floor: int = 0
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    limitations: list[str] = Field(default_factory=list)


def _resolve_fingerprints(
    evidence_ids: list[str], evidence_by_id: dict[str, EvidenceItem]
) -> list[str]:
    """Resolves this hypothesis's supporting evidence to shared_model fingerprints.

    Uses the single shared fingerprint implementation (shared/schemas/evidence_ledger.py)
    rather than a private reimplementation, so merging here stays consistent with
    the Evidence Ledger's own corroboration detection.
    """
    return [
        compute_fingerprint(evidence_by_id[eid]) for eid in evidence_ids if eid in evidence_by_id
    ]


def collect_hypotheses(findings: dict[str, Finding]) -> list[MergedHypothesis]:
    collected: list[MergedHypothesis] = []
    for skill_name, finding in findings.items():
        evidence_by_id = {item.evidence_id: item for item in finding.evidence}
        for candidate in finding.possible_root_causes:
            collected.append(
                MergedHypothesis(
                    cause=candidate.cause,
                    contributing_skills=[skill_name],
                    supporting_evidence=[
                        EvidenceRef(skill_name=skill_name, evidence_id=eid)
                        for eid in candidate.supporting_evidence
                    ],
                    conflicting_evidence=[
                        EvidenceRef(skill_name=skill_name, evidence_id=eid)
                        for eid in candidate.conflicting_evidence
                    ],
                    local_confidences=[candidate.local_confidence],
                    fingerprints=_resolve_fingerprints(
                        candidate.supporting_evidence, evidence_by_id
                    ),
                )
            )
    return collected


def merge_hypotheses(hypotheses: list[MergedHypothesis]) -> list[MergedHypothesis]:
    """Merges hypotheses that share at least one resolved evidence fingerprint.

    Two hypotheses whose supporting evidence resolves to the same
    (subject, metric) fingerprint — even from different skills using
    different local evidence_id naming — are treated as independent
    corroboration of the same explanation, per evidence_model.md §5.1 and
    root_cause_analysis.md §2.3. Fingerprint equality, not evidence_id or
    skill-name equality, is the merge key.
    """
    remaining = list(hypotheses)
    merged: list[MergedHypothesis] = []

    while remaining:
        current = remaining.pop(0)
        current_fps = set(current.fingerprints)
        changed = True
        while changed:
            changed = False
            still_remaining: list[MergedHypothesis] = []
            for other in remaining:
                other_fps = set(other.fingerprints)
                if current_fps and other_fps and current_fps & other_fps:
                    current = MergedHypothesis(
                        cause=current.cause,
                        contributing_skills=[
                            *current.contributing_skills,
                            *other.contributing_skills,
                        ],
                        supporting_evidence=[
                            *current.supporting_evidence,
                            *other.supporting_evidence,
                        ],
                        conflicting_evidence=[
                            *current.conflicting_evidence,
                            *other.conflicting_evidence,
                        ],
                        local_confidences=[
                            *current.local_confidences,
                            *other.local_confidences,
                        ],
                        fingerprints=list(current_fps | other_fps),
                    )
                    current_fps = current_fps | other_fps
                    changed = True
                else:
                    still_remaining.append(other)
            remaining = still_remaining
        merged.append(current)

    return merged


def score_hypothesis(hypothesis: MergedHypothesis) -> float:
    base = sum(hypothesis.local_confidences) / len(hypothesis.local_confidences)
    num_contributing_skills = len(set(hypothesis.contributing_skills))
    corroboration_bonus = CORROBORATION_BONUS_PER_SKILL * (num_contributing_skills - 1)
    conflict_penalty = CONFLICT_PENALTY_PER_ITEM * len(hypothesis.conflicting_evidence)
    return max(0.0, min(1.0, base + corroboration_bonus - conflict_penalty))


def rank_hypotheses(hypotheses: list[MergedHypothesis]) -> tuple[list[MergedHypothesis], int]:
    scored = [h.model_copy(update={"score": score_hypothesis(h)}) for h in hypotheses]
    scored.sort(key=lambda h: h.score, reverse=True)

    published = [h for h in scored if h.score >= NOISE_FLOOR]
    dropped = len(scored) - len(published)
    return published, dropped


def _score_band(score: float) -> tuple[float, ConfidenceBand]:
    if score >= HIGH_SCORE_THRESHOLD:
        return 0.92, "high"
    if score >= MEDIUM_SCORE_THRESHOLD:
        return 0.65, "medium"
    return 0.3, "low"


def compute_ranking_confidence(ranked: list[MergedHypothesis]) -> tuple[float, ConfidenceBand]:
    """Derives this skill's own confidence in the ranking it just produced.

    A close score margin between two hypotheses is only genuine ambiguity —
    and thus confidence-reducing — when those hypotheses actually contradict
    each other (non-empty conflicting_evidence). Two hypotheses that remain
    separate after merge_hypotheses are, by construction, about *different*
    evidence (shared evidence would have merged them): several such
    hypotheses scoring similarly is multiple well-supported findings, per
    root_cause_analysis.md §4.1 ("Multiple Surviving Hypotheses Are Normal"),
    not an unresolved tie.
    """
    if not ranked:
        return 0.3, "low"

    if len(ranked) == 1:
        return _score_band(ranked[0].score)

    has_unresolved_conflict = any(h.conflicting_evidence for h in ranked)
    if not has_unresolved_conflict:
        return _score_band(ranked[0].score)

    top_score = ranked[0].score
    margin = ranked[0].score - ranked[1].score
    if margin >= HIGH_MARGIN_THRESHOLD and top_score >= HIGH_SCORE_THRESHOLD:
        return 0.92, "high"
    if margin >= MEDIUM_MARGIN_THRESHOLD:
        return 0.65, "medium"
    return 0.3, "low"


def run_root_cause_prioritization(findings: dict[str, Finding]) -> RankingResult:
    limitations: list[str] = []
    for skill_name, finding in findings.items():
        limitations.extend(f"[{skill_name}] {limitation}" for limitation in finding.limitations)

    if not findings:
        limitations.append("No skill findings were supplied to rank.")

    raw_hypotheses = collect_hypotheses(findings)
    merged = merge_hypotheses(raw_hypotheses)
    ranked, dropped = rank_hypotheses(merged)

    if dropped:
        limitations.append(
            f"{dropped} hypothesis(es) fell below the noise floor ({NOISE_FLOOR}) and were "
            "excluded from the ranking."
        )

    confidence_score, confidence_band = compute_ranking_confidence(ranked)

    return RankingResult(
        ranked_hypotheses=ranked,
        dropped_below_noise_floor=dropped,
        confidence_score=confidence_score,
        confidence_band=confidence_band,
        limitations=limitations,
    )
