from __future__ import annotations

import numpy as np
import pandas as pd

_SEED = 20260704
_REFERENCE_N = 50_000
_CURRENT_N = 15_000

_DEVICE_TYPES = ["mobile", "desktop", "tablet"]
_DEVICE_PROBS = [0.6, 0.3, 0.1]

_DATASET_IDS = {"fraud_detection_xgboost"}


def _make_zipcodes(rng: np.random.Generator, n: int) -> np.ndarray:
    return rng.integers(10_000, 99_999, size=n).astype(str)


def _build_reference(dataset_id: str) -> pd.DataFrame:
    rng = np.random.default_rng(_SEED)
    zipcodes = _make_zipcodes(rng, _REFERENCE_N)
    null_mask = rng.random(_REFERENCE_N) < 0.0002
    zipcodes = zipcodes.astype(object)
    zipcodes[null_mask] = None
    return pd.DataFrame(
        {
            "user_zipcode": zipcodes,
            "transaction_amount": rng.normal(loc=45.0, scale=15.0, size=_REFERENCE_N).clip(min=0),
            "device_type": rng.choice(_DEVICE_TYPES, size=_REFERENCE_N, p=_DEVICE_PROBS),
        }
    )


def _build_current(dataset_id: str) -> pd.DataFrame:
    rng = np.random.default_rng(_SEED + 1)
    zipcodes = _make_zipcodes(rng, _CURRENT_N)
    null_mask = rng.random(_CURRENT_N) < 0.185
    zipcodes = zipcodes.astype(object)
    zipcodes[null_mask] = None
    return pd.DataFrame(
        {
            "user_zipcode": zipcodes,
            "transaction_amount": rng.normal(loc=120.0, scale=40.0, size=_CURRENT_N).clip(min=0),
            "device_type": rng.choice(_DEVICE_TYPES, size=_CURRENT_N, p=_DEVICE_PROBS),
        }
    )


def get_reference_dataset(dataset_id: str) -> pd.DataFrame:
    """Returns the fixed, deterministic reference (baseline) dataset for `dataset_id`."""
    if dataset_id not in _DATASET_IDS:
        raise ValueError(f"Unknown reference dataset_id: {dataset_id!r}")
    return _build_reference(dataset_id)


def get_current_dataset(dataset_id: str) -> pd.DataFrame:
    """Returns the fixed, deterministic current (evaluation window) dataset for `dataset_id`."""
    if dataset_id not in _DATASET_IDS:
        raise ValueError(f"Unknown current dataset_id: {dataset_id!r}")
    return _build_current(dataset_id)
