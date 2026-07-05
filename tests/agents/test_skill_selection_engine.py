from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agents.skill_selection_engine import SkillSelectionEngine
from shared.schemas.incident import AffectedSystem, IncidentSignature
from shared.skill_registry import SkillRegistry

_SIGNATURE = IncidentSignature(
    incident_id="INC-1",
    alert_type="DownstreamAccuracyDrop",
    severity="high",
    affected_system=AffectedSystem(
        system_type="model_serving", identifier="Fraud_Detection_XGBoost"
    ),
    detected_at=datetime.now(UTC),
    raw_trigger_ref="trigger:INC-1",
)

_SKILL_PARAMS: dict[str, dict[str, object]] = {
    "data_drift_analysis": {
        "reference_dataset_id": "fraud_detection_xgboost",
        "current_dataset_id": "fraud_detection_xgboost",
        "numerical_features": ["transaction_amount"],
        "categorical_features": ["user_zipcode"],
    },
    "model_performance_analysis": {"predictions_dataset_id": "fraud_detection_xgboost"},
}


def _engine() -> SkillSelectionEngine:
    registry = SkillRegistry()
    registry.scan_skills()
    return SkillSelectionEngine(registry)


def test_select_initial_wave_matches_both_investigative_skills() -> None:
    engine = _engine()
    plan = engine.select_initial_wave(_SIGNATURE, _SKILL_PARAMS)

    assert plan.wave_id == 0
    assert plan.execution_mode == "parallel"
    assert {s.skill_name for s in plan.selected_skills} == {
        "data_drift_analysis",
        "model_performance_analysis",
    }
    assert plan.continuation_signal == "awaiting_evidence"


def test_select_initial_wave_excludes_skill_missing_required_input() -> None:
    engine = _engine()
    plan = engine.select_initial_wave(
        _SIGNATURE, {"data_drift_analysis": _SKILL_PARAMS["data_drift_analysis"]}
    )

    selected_names = {s.skill_name for s in plan.selected_skills}
    assert "model_performance_analysis" not in selected_names
    excluded_names = {c.skill_name for c in plan.excluded_candidates}
    assert "model_performance_analysis" in excluded_names


def test_select_initial_wave_unknown_alert_terminates_unclassified() -> None:
    engine = _engine()
    signature = _SIGNATURE.model_copy(update={"alert_type": "NotARealAlert"})
    plan = engine.select_initial_wave(signature, {})

    assert plan.selected_skills == []
    assert plan.continuation_signal == "terminate"
    assert plan.termination_reason == "no_skill_matched"


def test_select_next_wave_after_investigative_wave_emits_terminal_wave() -> None:
    engine = _engine()
    already_executed = {"data_drift_analysis", "model_performance_analysis"}
    plan = engine.select_next_wave(
        wave_id=1, skill_parameters={}, already_executed=already_executed
    )

    assert plan.execution_mode == "sequential"
    assert [s.skill_name for s in plan.selected_skills] == [
        "root_cause_prioritization",
        "incident_summary",
    ]
    assert all(s.trigger_reason == "terminal" for s in plan.selected_skills)
    assert plan.continuation_signal == "awaiting_evidence"


def test_select_next_wave_after_terminal_wave_signals_terminate() -> None:
    engine = _engine()
    already_executed = {
        "data_drift_analysis",
        "model_performance_analysis",
        "root_cause_prioritization",
        "incident_summary",
    }
    plan = engine.select_next_wave(
        wave_id=2, skill_parameters={}, already_executed=already_executed
    )

    assert plan.selected_skills == []
    assert plan.continuation_signal == "terminate"
    assert plan.termination_reason == "investigation_complete"


def test_select_initial_wave_registry_unavailable() -> None:
    registry = SkillRegistry(skills_dir=Path("/nonexistent"))
    registry.scan_skills()
    engine = SkillSelectionEngine(registry)

    plan = engine.select_initial_wave(_SIGNATURE, {})
    assert plan.termination_reason == "registry_unavailable"
