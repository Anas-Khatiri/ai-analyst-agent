from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[2] / "skills" / "model_performance_analysis" / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

import _model_performance_analysis_core as core  # noqa: E402
from run_model_performance_analysis import (  # noqa: E402
    ModelPerformanceAnalysisInput,
    run,
)


def test_compute_binary_metrics_known_confusion_counts() -> None:
    y_true = np.array([1, 1, 1, 1, 0, 0, 0, 0])
    y_pred = np.array([1, 1, 0, 0, 0, 0, 1, 1])
    metrics = core.compute_binary_metrics(y_true, y_pred)

    assert metrics.recall == pytest.approx(0.5)
    assert metrics.precision == pytest.approx(0.5)
    assert metrics.fpr == pytest.approx(0.5)
    assert metrics.accuracy == pytest.approx(0.5)


def test_bootstrap_metric_ci_contains_point_estimate() -> None:
    rng = np.random.default_rng(1)
    y_true = rng.integers(0, 2, size=500)
    y_pred = y_true.copy()
    low, high = core.bootstrap_metric_ci(y_true, y_pred, "recall", n_resamples=200)

    assert low <= 1.0 <= high + 1e-9


def test_compute_degraded_metrics_flags_recall_drop() -> None:
    global_metrics = core.BinaryMetrics(
        accuracy=0.96, precision=0.85, recall=0.73, f1_score=0.79, fpr=0.01, fnr=0.27
    )
    baseline = {"accuracy": 0.95, "precision": 0.90, "recall": 0.94, "f1_score": 0.92}
    degraded = core.compute_degraded_metrics(global_metrics, baseline, list(baseline.keys()))

    assert "recall" in degraded
    assert "f1_score" in degraded
    assert "accuracy" not in degraded


def test_is_localized_regression_true_for_single_collapsed_cohort() -> None:
    cohorts = [
        core.CohortResult(
            cohort_name="ios",
            n=2000,
            metrics=core.compute_binary_metrics(np.ones(2000), np.ones(2000)),
        ),
        core.CohortResult(
            cohort_name="android_v12",
            n=2000,
            metrics=core.compute_binary_metrics(
                np.ones(2000), np.concatenate([np.ones(300), np.zeros(1700)])
            ),
        ),
    ]
    worst = core.identify_worst_segment(cohorts, "recall")
    assert worst is not None
    assert worst.cohort_name == "android_v12"
    assert core.is_localized_regression(
        cohorts, worst, baseline_value=0.85, primary_metric="recall"
    )


def test_is_localized_regression_false_for_uniform_cohorts() -> None:
    y_true = np.ones(1000)
    y_pred = np.concatenate([np.ones(700), np.zeros(300)])
    metrics = core.compute_binary_metrics(y_true, y_pred)
    cohorts = [
        core.CohortResult(cohort_name="a", n=1000, metrics=metrics),
        core.CohortResult(cohort_name="b", n=1000, metrics=metrics),
    ]
    worst = core.identify_worst_segment(cohorts, "recall")
    assert worst is not None
    assert not core.is_localized_regression(
        cohorts, worst, baseline_value=0.94, primary_metric="recall"
    )


def test_compute_confidence_low_on_small_sample() -> None:
    score, band = core.compute_confidence(
        label_completeness=0.95, matched_n=50, is_statistically_significant=True
    )
    assert band == "low"
    assert score < 0.5


def test_compute_confidence_low_on_low_label_completeness() -> None:
    score, band = core.compute_confidence(
        label_completeness=0.02, matched_n=10_000, is_statistically_significant=True
    )
    assert band == "low"
    assert score < 0.5


def test_compute_confidence_high_when_significant_and_sufficient() -> None:
    score, band = core.compute_confidence(
        label_completeness=0.99, matched_n=15_000, is_statistically_significant=True
    )
    assert band == "high"
    assert score >= 0.8


def test_model_performance_analysis_input_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ModelPerformanceAnalysisInput.model_validate(
            {
                "predictions_dataset_id": "fraud_detection_xgboost",
                "unexpected_field": "should not be allowed",
            }
        )


async def test_run_detects_global_dataset_wide_regression() -> None:
    finding = await run(predictions_dataset_id="fraud_detection_xgboost")

    assert finding.confidence_score >= 0.8
    causes = [c.cause for c in finding.possible_root_causes]
    assert any("dataset-wide" in cause or "Global" in cause for cause in causes)
    assert not any("android" in cause for cause in causes)
    assert any(
        "fallback" in a.description or "retraining" in a.description
        for a in finding.recommended_actions
    )


async def test_run_detects_localized_cohort_regression() -> None:
    finding = await run(predictions_dataset_id="recommendation_engine_v3")

    assert finding.confidence_score >= 0.8
    causes = [c.cause for c in finding.possible_root_causes]
    assert any("android_v12" in cause for cause in causes)
    assert any("android_v12" in a.description for a in finding.recommended_actions)


async def test_run_low_confidence_on_label_lag_scenario() -> None:
    finding = await run(predictions_dataset_id="label_lag_scenario")

    assert finding.confidence_score < 0.5
    assert any("label" in limitation.lower() for limitation in finding.limitations)


async def test_run_rejects_unknown_dataset_id() -> None:
    with pytest.raises(ValueError, match="Unknown predictions dataset_id"):
        await run(predictions_dataset_id="not_a_real_dataset")
