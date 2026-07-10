from __future__ import annotations

from datetime import UTC, datetime

import _model_performance_analysis_core as core
from pydantic import BaseModel, ConfigDict, Field

from domain.finding import (
    ActionItem,
    EvidenceItem,
    Finding,
    HypothesisCandidate,
    TimeWindow,
)
from infra.tools import prediction_access

SKILL_NAME = "model_performance_analysis"
DEFAULT_PRIMARY_METRICS = ["accuracy", "precision", "recall", "f1_score", "fpr", "fnr"]


class ModelPerformanceAnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predictions_dataset_id: str
    primary_metrics: list[str] = Field(default_factory=lambda: list(DEFAULT_PRIMARY_METRICS))
    primary_metric: core.MetricName = "recall"
    cohort_column: str | None = "cohort"
    min_sample_size: int = 100


def _build_evidence(
    result: core.PerformanceComputationResult, window: TimeWindow
) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    evidence.append(
        EvidenceItem(
            evidence_id="label_completeness_ratio",
            subject="labels",
            metric="label_completeness_ratio",
            value=result.label_completeness_ratio,
            baseline=None,
            time_window=window,
            source_skill=SKILL_NAME,
        )
    )
    for metric_name in result.degraded_metrics_list:
        evidence.append(
            EvidenceItem(
                evidence_id=f"global_{metric_name}",
                subject="global",
                metric=metric_name,
                value=result.global_metrics.value(metric_name),
                baseline=result.baseline_metrics.get(metric_name),
                time_window=window,
                source_skill=SKILL_NAME,
            )
        )
    if result.worst_performing_segment is not None:
        segment = result.worst_performing_segment
        evidence.append(
            EvidenceItem(
                evidence_id=f"{segment.cohort_name}_{result.primary_metric}",
                subject=segment.cohort_name,
                metric=result.primary_metric,
                value=segment.metrics.value(result.primary_metric),
                baseline=result.baseline_metrics.get(result.primary_metric),
                time_window=window,
                source_skill=SKILL_NAME,
            )
        )
    return evidence


def _build_hypotheses(result: core.PerformanceComputationResult) -> list[HypothesisCandidate]:
    if not result.performance_degraded:
        return []

    if result.is_localized_regression and result.worst_performing_segment is not None:
        segment = result.worst_performing_segment
        return [
            HypothesisCandidate(
                cause=(
                    f"Localized performance regression isolated to cohort "
                    f"'{segment.cohort_name}' ({result.primary_metric}="
                    f"{segment.metrics.value(result.primary_metric):.4f} vs baseline "
                    f"{result.baseline_metrics.get(result.primary_metric)}), while other "
                    f"cohorts remain near baseline."
                ),
                supporting_evidence=[f"{segment.cohort_name}_{result.primary_metric}"],
                local_confidence=result.confidence_score,
            )
        ]

    return [
        HypothesisCandidate(
            cause=(
                "Global, dataset-wide performance regression affecting all cohorts uniformly "
                f"(degraded metrics: {', '.join(result.degraded_metrics_list)})."
            ),
            supporting_evidence=[f"global_{m}" for m in result.degraded_metrics_list],
            local_confidence=result.confidence_score,
        )
    ]


def _build_actions(result: core.PerformanceComputationResult) -> tuple[list[ActionItem], list[str]]:
    if not result.performance_degraded:
        return [], []

    if result.is_localized_regression and result.worst_performing_segment is not None:
        segment_name = result.worst_performing_segment.cohort_name
        return (
            [
                ActionItem(
                    description=f"Bypass model predictions for cohort '{segment_name}'.",
                    risk_tier="requires_approval",
                    justifying_finding_refs=[f"{segment_name}_{result.primary_metric}"],
                    time_horizon="immediate",
                ),
                ActionItem(
                    description=f"Audit feature serialization for cohort '{segment_name}'.",
                    risk_tier="requires_approval",
                    justifying_finding_refs=[f"{segment_name}_{result.primary_metric}"],
                    time_horizon="medium_term",
                ),
            ],
            ["Add integration tests validating feature schemas across all cohorts."],
        )

    return (
        [
            ActionItem(
                description="Route traffic to a fallback or rule-based model.",
                risk_tier="requires_approval",
                justifying_finding_refs=[f"global_{m}" for m in result.degraded_metrics_list],
                time_horizon="immediate",
            ),
            ActionItem(
                description="Schedule a retraining run using the newly labeled data.",
                risk_tier="requires_approval",
                justifying_finding_refs=[f"global_{m}" for m in result.degraded_metrics_list],
                time_horizon="medium_term",
            ),
        ],
        ["Implement a shadow deployment pipeline to validate performance before full rollout."],
    )


async def run(**params: object) -> Finding:
    """Entrypoint contract per DYNAMIC_DISCOVERY_DESIGN.md §3.3: a module-level `run()`."""
    validated = ModelPerformanceAnalysisInput.model_validate(params)

    predictions = await prediction_access.load_predictions(validated.predictions_dataset_id)
    baseline_metrics = await prediction_access.load_baseline_metrics(
        validated.predictions_dataset_id
    )

    result = core.run_performance_analysis(
        predictions=predictions,
        baseline_metrics=baseline_metrics,
        primary_metrics=validated.primary_metrics,
        cohort_column=validated.cohort_column,
        primary_metric=validated.primary_metric,
        min_sample_size=validated.min_sample_size,
    )

    now = datetime.now(UTC)
    window = TimeWindow(start=now, end=now)
    actions, preventive_actions = _build_actions(result)

    summary = (
        f"Model performance {'degraded' if result.performance_degraded else 'stable'} "
        f"({result.matched_n} matched records, "
        f"{result.label_completeness_ratio:.1%} label completeness). "
        + (
            f"Degraded metrics: {', '.join(result.degraded_metrics_list)}."
            if result.degraded_metrics_list
            else "No metrics breached the degradation threshold."
        )
    )

    return Finding(
        investigation_summary=summary,
        evidence=_build_evidence(result, window),
        possible_root_causes=_build_hypotheses(result),
        confidence_score=result.confidence_score,
        recommended_actions=actions,
        preventive_actions=preventive_actions,
        limitations=result.limitations,
    )
