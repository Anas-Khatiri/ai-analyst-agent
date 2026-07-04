from __future__ import annotations

import numpy as np
import pandas as pd

_SEED = 20260704

_DATASET_IDS = {"fraud_detection_xgboost", "recommendation_engine_v3", "label_lag_scenario"}

_BASELINE_METRICS: dict[str, dict[str, float]] = {
    "fraud_detection_xgboost": {
        "accuracy": 0.95,
        "precision": 0.90,
        "recall": 0.94,
        "f1_score": 0.92,
        "fpr": 0.03,
        "fnr": 0.06,
    },
    "recommendation_engine_v3": {
        "accuracy": 0.88,
        "precision": 0.83,
        "recall": 0.85,
        "f1_score": 0.84,
        "fpr": 0.05,
        "fnr": 0.15,
    },
    "label_lag_scenario": {
        "accuracy": 0.95,
        "precision": 0.90,
        "recall": 0.94,
        "f1_score": 0.92,
        "fpr": 0.03,
        "fnr": 0.06,
    },
}


def _cohort_block(
    rng: np.random.Generator, cohort: str, n_pos: int, n_neg: int, tp: int, fp: int
) -> pd.DataFrame:
    """Builds a deterministic (y_true, y_pred, cohort) block from exact confusion counts."""
    fn = n_pos - tp
    tn = n_neg - fp
    y_true = np.concatenate([np.ones(n_pos, dtype=int), np.zeros(n_neg, dtype=int)])
    y_pred = np.concatenate(
        [
            np.ones(tp, dtype=int),
            np.zeros(fn, dtype=int),
            np.ones(fp, dtype=int),
            np.zeros(tn, dtype=int),
        ]
    )
    order = rng.permutation(len(y_true))
    return pd.DataFrame(
        {
            "y_true": y_true[order],
            "y_pred": y_pred[order],
            "cohort": cohort,
        }
    )


def _build_fraud_detection_xgboost() -> pd.DataFrame:
    rng = np.random.default_rng(_SEED)
    blocks = [
        _cohort_block(rng, cohort, n_pos=500, n_neg=4500, tp=367, fp=67)
        for cohort in ("mobile", "desktop", "tablet")
    ]
    df = pd.concat(blocks, ignore_index=True)
    df.insert(0, "request_id", [f"req_{i}" for i in range(len(df))])
    return df


def _build_recommendation_engine_v3() -> pd.DataFrame:
    rng = np.random.default_rng(_SEED + 1)
    stable = [
        _cohort_block(rng, cohort, n_pos=2000, n_neg=3000, tp=1720, fp=150)
        for cohort in ("ios", "desktop", "android_other")
    ]
    collapsed = _cohort_block(rng, "android_v12", n_pos=2000, n_neg=3000, tp=300, fp=150)
    df = pd.concat([*stable, collapsed], ignore_index=True)
    df.insert(0, "request_id", [f"req_{i}" for i in range(len(df))])
    return df


def _build_label_lag_scenario() -> pd.DataFrame:
    rng = np.random.default_rng(_SEED + 2)
    df = _build_fraud_detection_xgboost()
    matched_mask = rng.random(len(df)) < 0.02
    df.loc[~matched_mask, "y_true"] = np.nan
    return df


_BUILDERS = {
    "fraud_detection_xgboost": _build_fraud_detection_xgboost,
    "recommendation_engine_v3": _build_recommendation_engine_v3,
    "label_lag_scenario": _build_label_lag_scenario,
}


def get_predictions(dataset_id: str) -> pd.DataFrame:
    """Returns the fixed, deterministic prediction/label/cohort dataset for `dataset_id`."""
    if dataset_id not in _DATASET_IDS:
        raise ValueError(f"Unknown predictions dataset_id: {dataset_id!r}")
    return _BUILDERS[dataset_id]()


def get_baseline_metrics(dataset_id: str) -> dict[str, float]:
    """Returns the fixed baseline (training/shadow) metrics for `dataset_id`."""
    if dataset_id not in _DATASET_IDS:
        raise ValueError(f"Unknown baseline dataset_id: {dataset_id!r}")
    return dict(_BASELINE_METRICS[dataset_id])
