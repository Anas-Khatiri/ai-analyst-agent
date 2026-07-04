from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "data_drift_analysis" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import _data_drift_analysis_core as core  # noqa: E402
from run_data_drift_analysis import DataDriftAnalysisInput, run  # noqa: E402


def test_compute_null_rate() -> None:
    series = pd.Series([1, None, 2, None, 3])
    assert core.compute_null_rate(series) == pytest.approx(0.4)


def test_compute_null_rate_empty_series() -> None:
    assert core.compute_null_rate(pd.Series([], dtype=float)) == 0.0


def test_is_null_rate_spike() -> None:
    assert core.is_null_rate_spike(0.0002, 0.185) is True
    assert core.is_null_rate_spike(0.01, 0.02) is False


def test_analyze_numerical_feature_detects_drift() -> None:
    reference = pd.Series(range(1000)).astype(float) * 0.1 + 45.0
    current = pd.Series(range(1000)).astype(float) * 0.1 + 120.0
    result = core.analyze_numerical_feature("transaction_amount", reference, current)

    assert result.drifted is True
    assert result.psi > core.PSI_SEVERE_THRESHOLD
    assert result.p_value < core.DEFAULT_P_VALUE_THRESHOLD


def test_analyze_numerical_feature_no_drift_on_identical_distribution() -> None:
    reference = pd.Series(range(500)).astype(float)
    current = pd.Series(range(500)).astype(float)
    result = core.analyze_numerical_feature("stable_feature", reference, current)

    assert result.drifted is False
    assert result.psi < core.PSI_MODERATE_THRESHOLD


def test_analyze_categorical_feature_no_drift_on_identical_distribution() -> None:
    reference = pd.Series(["mobile", "desktop", "tablet"] * 200)
    current = pd.Series(["mobile", "desktop", "tablet"] * 100)
    result = core.analyze_categorical_feature("device_type", reference, current)

    assert result.drifted is False


def test_analyze_categorical_feature_detects_null_spike() -> None:
    reference = pd.Series(["10001"] * 998 + [None, None])
    current = pd.Series(["10001"] * 500 + [None] * 500)
    result = core.analyze_categorical_feature("user_zipcode", reference, current)

    assert result.null_rate_spike is True
    assert result.drifted is True


def test_compute_confidence_low_on_small_sample() -> None:
    score, band = core.compute_confidence(50, 50, [], min_sample_size=100)
    assert band == "low"
    assert score < 0.5


def test_run_drift_analysis_records_limitation_for_missing_feature() -> None:
    reference = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    current = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    result = core.run_drift_analysis(
        reference=reference,
        current=current,
        numerical_features=["a", "missing_feature"],
        categorical_features=[],
        min_sample_size=1,
    )

    assert any("missing_feature" in limitation for limitation in result.limitations)
    assert len(result.feature_results) == 1


def test_data_drift_analysis_input_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DataDriftAnalysisInput.model_validate(
            {
                "reference_dataset_id": "fraud_detection_xgboost",
                "current_dataset_id": "fraud_detection_xgboost",
                "numerical_features": [],
                "unexpected_field": "should not be allowed",
            }
        )


async def test_run_end_to_end_matches_documented_fraud_scenario() -> None:
    finding = await run(
        reference_dataset_id="fraud_detection_xgboost",
        current_dataset_id="fraud_detection_xgboost",
        numerical_features=["transaction_amount"],
        categorical_features=["user_zipcode", "device_type"],
        min_sample_size=100,
    )

    assert finding.confidence_score >= 0.8
    causes = [c.cause for c in finding.possible_root_causes]
    assert any("user_zipcode" in cause for cause in causes)
    assert any("transaction_amount" in cause for cause in causes)
    assert not any("device_type" in cause for cause in causes)

    action_descriptions = [a.description for a in finding.recommended_actions]
    assert any("imputation" in description for description in action_descriptions)
    assert all(
        a.risk_tier in ("auto_executable", "requires_approval") for a in finding.recommended_actions
    )


async def test_run_rejects_unknown_dataset_id() -> None:
    with pytest.raises(ValueError, match="Unknown reference dataset_id"):
        await run(
            reference_dataset_id="not_a_real_dataset",
            current_dataset_id="fraud_detection_xgboost",
            numerical_features=["transaction_amount"],
            categorical_features=[],
        )
