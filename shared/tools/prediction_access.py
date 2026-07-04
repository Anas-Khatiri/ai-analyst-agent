from __future__ import annotations

import pandas as pd

from services.mock_env import prediction_store


async def load_predictions(dataset_id: str) -> pd.DataFrame:
    """Loads matched prediction/label/cohort records for `dataset_id`.

    Per ADR-002, this signature is the permanent interface skills call; only
    the implementation swaps when real infrastructure replaces the mock adapter.
    """
    return prediction_store.get_predictions(dataset_id)


async def load_baseline_metrics(dataset_id: str) -> dict[str, float]:
    """Loads the saved baseline (training/shadow) performance metrics for `dataset_id`."""
    return prediction_store.get_baseline_metrics(dataset_id)
