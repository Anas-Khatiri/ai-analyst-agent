from __future__ import annotations

from agents.skill_selection_engine import SkillSelectionEngine
from shared.skill_registry import SkillRegistry


def _engine() -> SkillSelectionEngine:
    registry = SkillRegistry()
    registry.scan_skills()
    return SkillSelectionEngine(registry)


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
