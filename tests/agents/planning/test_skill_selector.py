from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from google.genai.errors import ServerError

from agents.planning.skill_selector import SkillSelectionResult, SkillSelector, _filter_runnable
from domain.incident import AffectedSystem, IncidentSignature
from infra.skill_registry import SkillRegistry

_LIVE_API_RETRIES = 3
_LIVE_API_RETRY_DELAY_SECONDS = 5.0


async def _select_with_retry(
    selector: SkillSelector,
    signature: IncidentSignature,
    skill_parameters: dict[str, dict[str, object]],
) -> SkillSelectionResult:
    """Retries only on a known-transient upstream 503 (Gemini API capacity),
    mirroring tests/agents/test_react_agent.py::_analyze_incident_react_with_retry."""
    last_error: ServerError | None = None
    for attempt in range(_LIVE_API_RETRIES):
        try:
            return await selector.select(signature, skill_parameters)
        except ServerError as exc:
            if exc.code != 503:
                raise
            last_error = exc
            if attempt < _LIVE_API_RETRIES - 1:
                await asyncio.sleep(_LIVE_API_RETRY_DELAY_SECONDS)
    assert last_error is not None
    raise last_error


def _signature() -> IncidentSignature:
    return IncidentSignature(
        incident_id="INC-1",
        alert_type="DownstreamAccuracyDrop",
        severity="high",
        affected_system=AffectedSystem(
            system_type="model_serving", identifier="Fraud_Detection_XGBoost"
        ),
        detected_at=datetime.now(UTC),
        raw_trigger_ref="trigger:INC-1",
    )


def _registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.scan_skills()
    return registry


def _has_real_api_key() -> bool:
    key = os.getenv("GEMINI_API_KEY")
    return bool(key) and key != "your_gemini_api_key_here"


async def test_select_skips_llm_call_when_no_skill_is_runnable() -> None:
    # No skill_parameters supplied at all -> both investigative skills are
    # missing every required input, so the deterministic pre-filter must
    # short-circuit before ever touching the model. An invalid model name
    # would raise if the code path actually tried to call it.
    selector = SkillSelector(_registry(), model="this-model-does-not-exist")

    result = await selector.select(_signature(), skill_parameters={})

    assert result.selected_skill_names == []
    assert {r.skill_name for r in result.records} == {
        "data_drift_analysis",
        "model_performance_analysis",
    }
    for record in result.records:
        assert record.excluded is True
        assert record.trigger_reason == "llm_selected"
        assert record.wave_index == 0
        assert record.exclusion_reason is not None
        assert record.exclusion_reason.startswith("required input(s) not supplied")


def test_filter_runnable_separates_runnable_from_missing_inputs() -> None:
    # Pure unit test of the deterministic pre-filter, no LLM involved:
    # model_performance_analysis has everything it needs,
    # data_drift_analysis is missing all of its required inputs.
    candidates = _registry().investigative_skills()
    skill_parameters: dict[str, dict[str, object]] = {
        "model_performance_analysis": {"predictions_dataset_id": "fraud_detection_xgboost"}
    }

    runnable, records = _filter_runnable(candidates, skill_parameters)

    assert {meta.name for meta in runnable} == {"model_performance_analysis"}
    assert len(records) == 1
    assert records[0].skill_name == "data_drift_analysis"
    assert records[0].excluded is True
    assert records[0].exclusion_reason is not None
    assert records[0].exclusion_reason.startswith("required input(s) not supplied")


@pytest.mark.skipif(not _has_real_api_key(), reason="requires a real GEMINI_API_KEY")
async def test_select_live_returns_subset_of_real_catalog() -> None:
    selector = SkillSelector(_registry(), model="gemini-3.5-flash")
    skill_parameters: dict[str, dict[str, object]] = {
        "data_drift_analysis": {
            "reference_dataset_id": "fraud_detection_xgboost",
            "current_dataset_id": "fraud_detection_xgboost",
            "numerical_features": ["transaction_amount"],
            "categorical_features": ["user_zipcode", "device_type"],
        },
        "model_performance_analysis": {"predictions_dataset_id": "fraud_detection_xgboost"},
    }

    result = await _select_with_retry(selector, _signature(), skill_parameters)

    # Structural assertions only, per .agents/CONTEXT.md §4 -- never assert
    # which specific skill(s) the model chose.
    catalog_names = {"data_drift_analysis", "model_performance_analysis"}
    assert set(result.selected_skill_names) <= catalog_names
    assert {r.skill_name for r in result.records} <= catalog_names
