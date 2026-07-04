from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from scipy import stats

PSI_MODERATE_THRESHOLD = 0.1
PSI_SEVERE_THRESHOLD = 0.25
DEFAULT_P_VALUE_THRESHOLD = 0.05
STRONG_P_VALUE_THRESHOLD = 0.01
NULL_RATE_SPIKE_ABS_THRESHOLD = 0.05
LARGE_SAMPLE_THRESHOLD = 1000

FeatureType = Literal["numerical", "categorical"]
TestName = Literal["ks_test", "chi_square"]
ConfidenceBand = Literal["high", "medium", "low"]


class FeatureDriftResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_name: str
    feature_type: FeatureType
    reference_n: int
    current_n: int
    null_rate_reference: float
    null_rate_current: float
    null_rate_spike: bool
    test_name: TestName
    p_value: float
    psi: float
    drifted: bool


class DriftComputationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_drift_detected: bool
    drifted_feature_ratio: float
    feature_results: list[FeatureDriftResult] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    limitations: list[str] = Field(default_factory=list)


def compute_null_rate(series: pd.Series) -> float:
    if len(series) == 0:
        return 0.0
    return float(series.isna().mean())


def is_null_rate_spike(null_rate_reference: float, null_rate_current: float) -> bool:
    return (null_rate_current - null_rate_reference) > NULL_RATE_SPIKE_ABS_THRESHOLD


def compute_psi_numerical(reference: pd.Series, current: pd.Series, buckets: int = 10) -> float:
    ref = reference.dropna()
    cur = current.dropna()
    if ref.empty or cur.empty:
        return 0.0

    quantiles = np.linspace(0, 1, buckets + 1)
    breakpoints: list[float] = np.unique(ref.quantile(quantiles).to_numpy()).tolist()
    if len(breakpoints) < 3:
        return 0.0
    breakpoints[0] = -np.inf
    breakpoints[-1] = np.inf

    ref_binned = pd.cut(ref, bins=breakpoints)
    cur_binned = pd.cut(cur, bins=breakpoints)
    ref_pct = ref_binned.value_counts(sort=False) / len(ref)
    cur_pct = cur_binned.value_counts(sort=False) / len(cur)
    return _psi_from_distributions(ref_pct.to_numpy(), cur_pct.to_numpy())


def compute_psi_categorical(reference: pd.Series, current: pd.Series) -> float:
    ref = reference.dropna()
    cur = current.dropna()
    if ref.empty or cur.empty:
        return 0.0

    categories = sorted(set(ref.unique()) | set(cur.unique()))
    ref_counts = ref.value_counts()
    cur_counts = cur.value_counts()
    ref_pct = np.array([ref_counts.get(c, 0) / len(ref) for c in categories])
    cur_pct = np.array([cur_counts.get(c, 0) / len(cur) for c in categories])
    return _psi_from_distributions(ref_pct, cur_pct)


def _psi_from_distributions(ref_pct: np.ndarray, cur_pct: np.ndarray) -> float:
    ref_pct = np.where(ref_pct == 0, 1e-6, ref_pct)
    cur_pct = np.where(cur_pct == 0, 1e-6, cur_pct)
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def analyze_numerical_feature(
    feature_name: str,
    reference: pd.Series,
    current: pd.Series,
    p_value_threshold: float = DEFAULT_P_VALUE_THRESHOLD,
) -> FeatureDriftResult:
    null_rate_reference = compute_null_rate(reference)
    null_rate_current = compute_null_rate(current)
    null_spike = is_null_rate_spike(null_rate_reference, null_rate_current)

    ref_clean = reference.dropna()
    cur_clean = current.dropna()
    ks_result = stats.ks_2samp(ref_clean.to_numpy(), cur_clean.to_numpy())
    psi = compute_psi_numerical(reference, current)
    p_value = float(ks_result.pvalue)

    drifted = null_spike or p_value < p_value_threshold or psi >= PSI_MODERATE_THRESHOLD

    return FeatureDriftResult(
        feature_name=feature_name,
        feature_type="numerical",
        reference_n=len(reference),
        current_n=len(current),
        null_rate_reference=null_rate_reference,
        null_rate_current=null_rate_current,
        null_rate_spike=null_spike,
        test_name="ks_test",
        p_value=p_value,
        psi=psi,
        drifted=drifted,
    )


def analyze_categorical_feature(
    feature_name: str,
    reference: pd.Series,
    current: pd.Series,
    p_value_threshold: float = DEFAULT_P_VALUE_THRESHOLD,
) -> FeatureDriftResult:
    null_rate_reference = compute_null_rate(reference)
    null_rate_current = compute_null_rate(current)
    null_spike = is_null_rate_spike(null_rate_reference, null_rate_current)

    ref_clean = reference.dropna()
    cur_clean = current.dropna()
    categories = sorted(set(ref_clean.unique()) | set(cur_clean.unique()))
    p_value = 1.0
    if len(categories) > 1 and not ref_clean.empty and not cur_clean.empty:
        ref_counts = ref_clean.value_counts()
        cur_counts = cur_clean.value_counts()
        contingency = np.array(
            [
                [ref_counts.get(c, 0) for c in categories],
                [cur_counts.get(c, 0) for c in categories],
            ]
        )
        chi2_result = stats.chi2_contingency(contingency)
        p_value = float(chi2_result.pvalue)

    psi = compute_psi_categorical(reference, current)
    drifted = null_spike or p_value < p_value_threshold or psi >= PSI_MODERATE_THRESHOLD

    return FeatureDriftResult(
        feature_name=feature_name,
        feature_type="categorical",
        reference_n=len(reference),
        current_n=len(current),
        null_rate_reference=null_rate_reference,
        null_rate_current=null_rate_current,
        null_rate_spike=null_spike,
        test_name="chi_square",
        p_value=p_value,
        psi=psi,
        drifted=drifted,
    )


def compute_confidence(
    reference_n: int,
    current_n: int,
    feature_results: list[FeatureDriftResult],
    min_sample_size: int,
) -> tuple[float, ConfidenceBand]:
    if reference_n < min_sample_size or current_n < min_sample_size:
        return 0.3, "low"

    large_sample = reference_n > LARGE_SAMPLE_THRESHOLD and current_n > LARGE_SAMPLE_THRESHOLD

    has_strong_drift = any(
        f.psi >= PSI_SEVERE_THRESHOLD and f.p_value < STRONG_P_VALUE_THRESHOLD
        for f in feature_results
    )
    has_null_spike = any(f.null_rate_spike for f in feature_results)
    has_moderate_signal = any(
        PSI_MODERATE_THRESHOLD <= f.psi < PSI_SEVERE_THRESHOLD for f in feature_results
    )
    all_clearly_stable = all(
        f.psi < PSI_MODERATE_THRESHOLD
        and f.p_value >= DEFAULT_P_VALUE_THRESHOLD
        and not f.null_rate_spike
        for f in feature_results
    )

    if large_sample and (has_strong_drift or has_null_spike or all_clearly_stable):
        return 0.92, "high"
    if has_moderate_signal or has_strong_drift or has_null_spike:
        return 0.65, "medium"
    return 0.5, "medium"


def run_drift_analysis(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    numerical_features: list[str],
    categorical_features: list[str],
    p_value_threshold: float = DEFAULT_P_VALUE_THRESHOLD,
    min_sample_size: int = 100,
) -> DriftComputationResult:
    limitations: list[str] = []
    feature_results: list[FeatureDriftResult] = []

    for feature in numerical_features:
        if feature not in reference.columns or feature not in current.columns:
            limitations.append(f"Numerical feature '{feature}' missing from one or both datasets.")
            continue
        feature_results.append(
            analyze_numerical_feature(
                feature, reference[feature], current[feature], p_value_threshold
            )
        )

    for feature in categorical_features:
        if feature not in reference.columns or feature not in current.columns:
            limitations.append(
                f"Categorical feature '{feature}' missing from one or both datasets."
            )
            continue
        feature_results.append(
            analyze_categorical_feature(
                feature, reference[feature], current[feature], p_value_threshold
            )
        )

    if len(reference) < min_sample_size or len(current) < min_sample_size:
        limitations.append(
            f"Sample size below minimum ({min_sample_size}): "
            f"reference={len(reference)}, current={len(current)}."
        )

    drifted_count = sum(1 for f in feature_results if f.drifted)
    drifted_feature_ratio = drifted_count / len(feature_results) if feature_results else 0.0
    dataset_drift_detected = drifted_count > 0

    confidence_score, confidence_band = compute_confidence(
        len(reference), len(current), feature_results, min_sample_size
    )

    return DriftComputationResult(
        dataset_drift_detected=dataset_drift_detected,
        drifted_feature_ratio=drifted_feature_ratio,
        feature_results=feature_results,
        confidence_score=confidence_score,
        confidence_band=confidence_band,
        limitations=limitations,
    )
