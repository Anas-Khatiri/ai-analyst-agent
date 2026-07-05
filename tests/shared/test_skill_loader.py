from __future__ import annotations

from pathlib import Path

import pytest

from shared.schemas.finding import Finding
from shared.skill_loader import execute_skill, load_skill_script
from shared.skill_registry import SkillRegistry


def test_load_skill_script_returns_module_with_run_entrypoint() -> None:
    registry = SkillRegistry()
    registry.scan_skills()
    meta = registry.get("data_drift_analysis")
    assert meta is not None

    module = load_skill_script(registry.resolve_script_path(meta))
    assert hasattr(module, "run")


def test_load_skill_script_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_skill_script(Path("/nonexistent/script.py"))


async def test_execute_skill_dynamically_runs_data_drift_analysis() -> None:
    registry = SkillRegistry()
    registry.scan_skills()
    meta = registry.get("data_drift_analysis")
    assert meta is not None

    finding = await execute_skill(
        meta,
        registry.resolve_script_path(meta),
        {
            "reference_dataset_id": "fraud_detection_xgboost",
            "current_dataset_id": "fraud_detection_xgboost",
            "numerical_features": ["transaction_amount"],
            "categorical_features": ["user_zipcode", "device_type"],
            "min_sample_size": 100,
        },
    )

    assert isinstance(finding, Finding)
    assert finding.confidence_score >= 0.8


async def test_execute_skill_missing_entrypoint_raises(tmp_path: Path) -> None:
    bad_script = tmp_path / "bad_script.py"
    bad_script.write_text("x = 1\n")
    registry = SkillRegistry()
    registry.scan_skills()
    meta = registry.get("data_drift_analysis")
    assert meta is not None

    with pytest.raises(AttributeError):
        await execute_skill(meta, bad_script, {})
