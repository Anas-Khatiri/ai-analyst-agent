from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
for _skill in (
    "root_cause_prioritization",
    "data_drift_analysis",
    "model_performance_analysis",
):
    sys.path.insert(0, str(_SKILLS_DIR / _skill / "scripts"))

import _root_cause_prioritization_core as core  # noqa: E402
from run_data_drift_analysis import run as run_data_drift_analysis  # noqa: E402
from run_model_performance_analysis import run as run_model_performance_analysis  # noqa: E402
from run_root_cause_prioritization import RootCausePrioritizationInput, run  # noqa: E402

from domain.finding import (  # noqa: E402
    ActionItem,
    EvidenceItem,
    Finding,
    HypothesisCandidate,
    TimeWindow,
)

_WINDOW = TimeWindow(start=datetime.now(UTC), end=datetime.now(UTC))


def _finding_with_hypothesis(
    cause: str,
    evidence_ids: list[str],
    local_confidence: float,
    conflicting: list[str] | None = None,
) -> Finding:
    return Finding(
        investigation_summary="synthetic",
        evidence=[
            EvidenceItem(
                evidence_id=eid,
                subject=eid,
                metric="value",
                value=1.0,
                time_window=_WINDOW,
                source_skill="synthetic_skill",
            )
            for eid in evidence_ids
        ],
        possible_root_causes=[
            HypothesisCandidate(
                cause=cause,
                supporting_evidence=evidence_ids,
                conflicting_evidence=conflicting or [],
                local_confidence=local_confidence,
            )
        ],
        confidence_score=local_confidence,
        recommended_actions=[
            ActionItem(
                description=f"Fix {cause}",
                risk_tier="requires_approval",
                justifying_finding_refs=evidence_ids,
                time_horizon="immediate",
            )
        ],
        preventive_actions=[f"Prevent {cause} recurrence"],
        limitations=[],
    )


def test_collect_hypotheses_tags_originating_skill() -> None:
    findings = {
        "skill_a": _finding_with_hypothesis("cause A", ["a_evidence"], 0.9),
        "skill_b": _finding_with_hypothesis("cause B", ["b_evidence"], 0.8),
    }
    collected = core.collect_hypotheses(findings)

    assert len(collected) == 2
    assert {h.contributing_skills[0] for h in collected} == {"skill_a", "skill_b"}


def test_merge_hypotheses_merges_on_shared_evidence() -> None:
    hypotheses = core.collect_hypotheses(
        {
            "skill_a": _finding_with_hypothesis("shared cause", ["shared_evidence"], 0.9),
            "skill_b": _finding_with_hypothesis("shared cause", ["shared_evidence"], 0.8),
        }
    )
    merged = core.merge_hypotheses(hypotheses)

    assert len(merged) == 1
    assert set(merged[0].contributing_skills) == {"skill_a", "skill_b"}


def test_merge_hypotheses_no_merge_without_overlap() -> None:
    hypotheses = core.collect_hypotheses(
        {
            "skill_a": _finding_with_hypothesis("cause A", ["a_evidence"], 0.9),
            "skill_b": _finding_with_hypothesis("cause B", ["b_evidence"], 0.8),
        }
    )
    merged = core.merge_hypotheses(hypotheses)

    assert len(merged) == 2


def test_score_hypothesis_corroboration_bonus_exceeds_plain_average() -> None:
    hypotheses = core.collect_hypotheses(
        {
            "skill_a": _finding_with_hypothesis("shared cause", ["shared_evidence"], 0.8),
            "skill_b": _finding_with_hypothesis("shared cause", ["shared_evidence"], 0.8),
        }
    )
    merged = core.merge_hypotheses(hypotheses)
    score = core.score_hypothesis(merged[0])

    assert score > 0.8


def test_score_hypothesis_conflict_penalty_reduces_score() -> None:
    hypothesis = core.collect_hypotheses(
        {
            "skill_a": _finding_with_hypothesis(
                "disputed cause", ["a_evidence"], 0.9, conflicting=["a_conflict"]
            )
        }
    )[0]
    score = core.score_hypothesis(hypothesis)

    assert score < 0.9


def test_rank_hypotheses_drops_below_noise_floor() -> None:
    low_confidence = core.MergedHypothesis(
        cause="weak", contributing_skills=["s"], local_confidences=[0.05]
    )
    ranked, dropped = core.rank_hypotheses([low_confidence])

    assert ranked == []
    assert dropped == 1


def test_compute_ranking_confidence_empty_is_low() -> None:
    score, band = core.compute_ranking_confidence([])
    assert band == "low"
    assert score < 0.5


def test_compute_ranking_confidence_high_with_clear_margin() -> None:
    ranked = [
        core.MergedHypothesis(cause="a", contributing_skills=["s"], score=0.9),
        core.MergedHypothesis(cause="b", contributing_skills=["s"], score=0.4),
    ]
    score, band = core.compute_ranking_confidence(ranked)
    assert band == "high"
    assert score >= 0.8


def test_compute_ranking_confidence_low_on_near_tie_between_conflicting_hypotheses() -> None:
    ranked = [
        core.MergedHypothesis(
            cause="a",
            contributing_skills=["s"],
            score=0.82,
            conflicting_evidence=[core.EvidenceRef(skill_name="s", evidence_id="counter_evidence")],
        ),
        core.MergedHypothesis(cause="b", contributing_skills=["s"], score=0.80),
    ]
    _, band = core.compute_ranking_confidence(ranked)
    assert band == "low"


def test_compute_ranking_confidence_high_for_multiple_non_conflicting_hypotheses() -> None:
    """Several distinct, non-contradicting hypotheses scoring similarly is not an
    unresolved tie — merge_hypotheses already merged anything sharing evidence, so
    separate entries are inherently about different findings (root_cause_analysis.md §4.1)."""
    ranked = [
        core.MergedHypothesis(cause="a", contributing_skills=["s1"], score=0.92),
        core.MergedHypothesis(cause="b", contributing_skills=["s2"], score=0.92),
        core.MergedHypothesis(cause="c", contributing_skills=["s2"], score=0.92),
    ]
    score, band = core.compute_ranking_confidence(ranked)
    assert band == "high"
    assert score >= 0.8


def test_root_cause_prioritization_input_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RootCausePrioritizationInput.model_validate({"findings": {}, "unexpected_field": "x"})


async def test_run_with_no_findings_is_low_confidence() -> None:
    finding = await run(findings={})

    assert finding.confidence_score < 0.5
    assert finding.possible_root_causes == []
    assert any("no skill findings" in limitation.lower() for limitation in finding.limitations)


async def test_run_merges_corroborating_synthetic_findings() -> None:
    findings = {
        "skill_a": _finding_with_hypothesis("shared cause", ["shared_evidence"], 0.85),
        "skill_b": _finding_with_hypothesis("shared cause", ["shared_evidence"], 0.85),
    }
    finding = await run(findings=findings)

    assert len(finding.possible_root_causes) == 1
    assert finding.possible_root_causes[0].local_confidence > 0.85
    assert finding.confidence_score >= 0.8
    assert len(finding.recommended_actions) >= 1


async def test_run_end_to_end_chains_real_skill_outputs() -> None:
    drift_finding = await run_data_drift_analysis(
        reference_dataset_id="fraud_detection_xgboost",
        current_dataset_id="fraud_detection_xgboost",
        numerical_features=["transaction_amount"],
        categorical_features=["user_zipcode", "device_type"],
        min_sample_size=100,
    )
    performance_finding = await run_model_performance_analysis(
        predictions_dataset_id="fraud_detection_xgboost"
    )

    ranking = await run(
        findings={
            "data_drift_analysis": drift_finding,
            "model_performance_analysis": performance_finding,
        }
    )

    assert len(ranking.possible_root_causes) >= 2
    causes = [c.cause for c in ranking.possible_root_causes]
    assert any("user_zipcode" in cause for cause in causes)
    assert any("dataset-wide" in cause or "Global" in cause for cause in causes)
    assert ranking.confidence_score > 0.0
    assert ranking.investigation_summary
