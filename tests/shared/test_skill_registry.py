from __future__ import annotations

from pathlib import Path

from shared.skill_registry import SkillRegistry


def test_scan_skills_finds_all_four_skills() -> None:
    registry = SkillRegistry()
    registry.scan_skills()

    assert set(registry.registry.keys()) == {
        "data_drift_analysis",
        "model_performance_analysis",
        "root_cause_prioritization",
        "incident_summary",
    }


def test_resolve_skills_for_alert_matches_both_investigative_skills() -> None:
    registry = SkillRegistry()
    registry.scan_skills()

    matched = {meta.name for meta in registry.resolve_skills_for_alert("DownstreamAccuracyDrop")}
    assert matched == {"data_drift_analysis", "model_performance_analysis"}


def test_resolve_skills_for_alert_no_match_returns_empty() -> None:
    registry = SkillRegistry()
    registry.scan_skills()

    assert registry.resolve_skills_for_alert("NotARealAlert") == []


def test_terminal_skills_ordered_by_terminal_order() -> None:
    registry = SkillRegistry()
    registry.scan_skills()

    terminal = registry.terminal_skills()
    assert [meta.name for meta in terminal] == ["root_cause_prioritization", "incident_summary"]


def test_investigative_skills_have_no_terminal_order() -> None:
    registry = SkillRegistry()
    registry.scan_skills()

    for meta in registry.registry.values():
        if meta.role == "investigative":
            assert meta.terminal_order is None


def test_resolve_script_path_points_to_real_file() -> None:
    registry = SkillRegistry()
    registry.scan_skills()

    meta = registry.get("data_drift_analysis")
    assert meta is not None
    script_path = registry.resolve_script_path(meta)
    assert script_path.is_file()


def test_is_empty_before_scan() -> None:
    registry = SkillRegistry()
    assert registry.is_empty()


def test_scan_skills_ignores_directory_without_skill_md(tmp_path: Path) -> None:
    (tmp_path / "not_a_skill").mkdir()
    (tmp_path / "not_a_skill" / "readme.txt").write_text("hello")

    registry = SkillRegistry(skills_dir=tmp_path)
    registry.scan_skills()

    assert registry.is_empty()
