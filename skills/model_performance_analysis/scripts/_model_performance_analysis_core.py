from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

MetricName = Literal["accuracy", "precision", "recall", "f1_score", "fpr", "fnr"]
ConfidenceBand = Literal["high", "medium", "low"]

HIGHER_IS_BETTER: dict[MetricName, bool] = {
    "accuracy": True,
    "precision": True,
    "recall": True,
    "f1_score": True,
    "fpr": False,
    "fnr": False,
}

DEGRADATION_THRESHOLD = 0.05
LOCALIZED_WORST_GAP_MULTIPLIER = 3.0
LOCALIZED_OTHER_GAP_CEILING = 0.05
LARGE_SAMPLE_THRESHOLD = 500
SMALL_SAMPLE_THRESHOLD = 100
HIGH_LABEL_COMPLETENESS_THRESHOLD = 0.8
LOW_LABEL_COMPLETENESS_THRESHOLD = 0.4
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260704


class BinaryMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accuracy: float
    precision: float
    recall: float
    f1_score: float
    fpr: float
    fnr: float

    def value(self, metric: MetricName) -> float:
        return getattr(self, metric)  # type: ignore[no-any-return]


class CohortResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cohort_name: str
    n: int
    metrics: BinaryMetrics


class PerformanceComputationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_completeness_ratio: float
    matched_n: int
    global_metrics: BinaryMetrics
    baseline_metrics: dict[str, float]
    degraded_metrics_list: list[MetricName] = Field(default_factory=list)
    performance_degraded: bool
    primary_metric: MetricName
    primary_metric_ci_low: float
    primary_metric_ci_high: float
    is_statistically_significant: bool
    cohort_results: list[CohortResult] = Field(default_factory=list)
    worst_performing_segment: CohortResult | None = None
    is_localized_regression: bool
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    limitations: list[str] = Field(default_factory=list)


def compute_label_completeness(df: pd.DataFrame) -> float:
    if len(df) == 0:
        return 0.0
    return float(df["y_true"].notna().mean())


def compute_binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> BinaryMetrics:
    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    tn = int(np.sum((y_true == 0) & (y_pred == 0)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))

    total = tp + tn + fp + fn
    accuracy = (tp + tn) / total if total else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1_score = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    fnr = fn / (fn + tp) if (fn + tp) else 0.0

    return BinaryMetrics(
        accuracy=accuracy, precision=precision, recall=recall, f1_score=f1_score, fpr=fpr, fnr=fnr
    )


def bootstrap_metric_ci(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    metric: MetricName,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    ci_level: float = 0.95,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    if len(y_true) == 0:
        return 0.0, 0.0

    rng = np.random.default_rng(seed)
    n = len(y_true)
    samples = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        samples[i] = compute_binary_metrics(y_true[idx], y_pred[idx]).value(metric)

    alpha = (1.0 - ci_level) / 2.0
    low = float(np.quantile(samples, alpha))
    high = float(np.quantile(samples, 1.0 - alpha))
    return low, high


def compute_cohort_metrics(df: pd.DataFrame, cohort_column: str) -> list[CohortResult]:
    results: list[CohortResult] = []
    for cohort_name, group in df.groupby(cohort_column):
        matched = group.dropna(subset=["y_true"])
        y_true = matched["y_true"].to_numpy()
        y_pred = matched["y_pred"].to_numpy()
        results.append(
            CohortResult(
                cohort_name=str(cohort_name),
                n=len(matched),
                metrics=compute_binary_metrics(y_true, y_pred),
            )
        )
    return sorted(results, key=lambda r: r.cohort_name)


def identify_worst_segment(
    cohort_results: list[CohortResult], primary_metric: MetricName
) -> CohortResult | None:
    if not cohort_results:
        return None
    higher_is_better = HIGHER_IS_BETTER[primary_metric]
    return min(
        cohort_results,
        key=lambda r: (
            r.metrics.value(primary_metric)
            if higher_is_better
            else -r.metrics.value(primary_metric)
        ),
    )


def is_localized_regression(
    cohort_results: list[CohortResult],
    worst_segment: CohortResult | None,
    baseline_value: float,
    primary_metric: MetricName,
) -> bool:
    if worst_segment is None or len(cohort_results) < 2:
        return False

    higher_is_better = HIGHER_IS_BETTER[primary_metric]
    other_cohorts = [r for r in cohort_results if r.cohort_name != worst_segment.cohort_name]
    if not other_cohorts:
        return False

    def gap(value: float) -> float:
        raw = (baseline_value - value) if higher_is_better else (value - baseline_value)
        return max(raw, 0.0)

    worst_gap = gap(worst_segment.metrics.value(primary_metric))
    other_gap_avg = float(np.mean([gap(r.metrics.value(primary_metric)) for r in other_cohorts]))

    return (
        other_gap_avg < LOCALIZED_OTHER_GAP_CEILING
        and worst_gap > LOCALIZED_WORST_GAP_MULTIPLIER * max(other_gap_avg, 1e-6)
    )


def compute_degraded_metrics(
    global_metrics: BinaryMetrics, baseline_metrics: dict[str, float], primary_metrics: list[str]
) -> list[MetricName]:
    degraded: list[MetricName] = []
    for metric in primary_metrics:
        if metric not in HIGHER_IS_BETTER or metric not in baseline_metrics:
            continue
        metric_name: MetricName = metric
        current = global_metrics.value(metric_name)
        baseline = baseline_metrics[metric]
        higher_is_better = HIGHER_IS_BETTER[metric_name]
        delta = (baseline - current) if higher_is_better else (current - baseline)
        if delta > DEGRADATION_THRESHOLD:
            degraded.append(metric_name)
    return degraded


def compute_confidence(
    label_completeness: float,
    matched_n: int,
    is_statistically_significant: bool,
) -> tuple[float, ConfidenceBand]:
    if label_completeness < LOW_LABEL_COMPLETENESS_THRESHOLD or matched_n < SMALL_SAMPLE_THRESHOLD:
        return 0.3, "low"
    if (
        label_completeness >= HIGH_LABEL_COMPLETENESS_THRESHOLD
        and matched_n > LARGE_SAMPLE_THRESHOLD
        and is_statistically_significant
    ):
        return 0.92, "high"
    return 0.65, "medium"


def run_performance_analysis(
    predictions: pd.DataFrame,
    baseline_metrics: dict[str, float],
    primary_metrics: list[str],
    cohort_column: str | None,
    primary_metric: MetricName = "recall",
    min_sample_size: int = 100,
) -> PerformanceComputationResult:
    limitations: list[str] = []
    label_completeness = compute_label_completeness(predictions)

    matched = predictions.dropna(subset=["y_true"])
    y_true = matched["y_true"].to_numpy()
    y_pred = matched["y_pred"].to_numpy()
    matched_n = len(matched)

    if matched_n < min_sample_size:
        limitations.append(
            f"Matched sample size below minimum ({min_sample_size}): {matched_n} records."
        )
    if label_completeness < LOW_LABEL_COMPLETENESS_THRESHOLD:
        limitations.append(
            f"Label completeness ({label_completeness:.2%}) is too low for a reliable evaluation."
        )

    global_metrics = compute_binary_metrics(y_true, y_pred)
    degraded_metrics_list = compute_degraded_metrics(
        global_metrics, baseline_metrics, primary_metrics
    )
    performance_degraded = len(degraded_metrics_list) > 0

    ci_low, ci_high = bootstrap_metric_ci(y_true, y_pred, primary_metric)
    baseline_primary = baseline_metrics.get(primary_metric)
    is_significant = baseline_primary is not None and not (ci_low <= baseline_primary <= ci_high)

    cohort_results: list[CohortResult] = []
    worst_segment: CohortResult | None = None
    localized = False
    if cohort_column is not None and cohort_column in predictions.columns:
        cohort_results = compute_cohort_metrics(matched, cohort_column)
        worst_segment = identify_worst_segment(cohort_results, primary_metric)
        if worst_segment is not None and baseline_primary is not None:
            localized = is_localized_regression(
                cohort_results, worst_segment, baseline_primary, primary_metric
            )

    confidence_score, confidence_band = compute_confidence(
        label_completeness, matched_n, is_significant
    )

    return PerformanceComputationResult(
        label_completeness_ratio=label_completeness,
        matched_n=matched_n,
        global_metrics=global_metrics,
        baseline_metrics=baseline_metrics,
        degraded_metrics_list=degraded_metrics_list,
        performance_degraded=performance_degraded,
        primary_metric=primary_metric,
        primary_metric_ci_low=ci_low,
        primary_metric_ci_high=ci_high,
        is_statistically_significant=is_significant,
        cohort_results=cohort_results,
        worst_performing_segment=worst_segment,
        is_localized_regression=localized,
        confidence_score=confidence_score,
        confidence_band=confidence_band,
        limitations=limitations,
    )
