from __future__ import annotations

import pandas as pd

from services.mock_env import dataset_store


async def load_reference_dataset(dataset_id: str) -> pd.DataFrame:
    """Loads the reference (baseline) dataset for `dataset_id`.

    Per ADR-002, this signature is the permanent interface skills call; only
    the implementation swaps when real infrastructure replaces the mock adapter.
    """
    return dataset_store.get_reference_dataset(dataset_id)


async def load_current_dataset(dataset_id: str) -> pd.DataFrame:
    """Loads the current (evaluation window) dataset for `dataset_id`."""
    return dataset_store.get_current_dataset(dataset_id)
