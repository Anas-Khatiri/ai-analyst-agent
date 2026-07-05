from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from google.genai.errors import ServerError

from agents.ml_analyst_agent import InvestigationSession
from agents.react_agent import analyze_incident_react, build_investigative_tools
from shared.schemas.incident import IncidentReport
from shared.skill_registry import SkillRegistry

_LIVE_API_RETRIES = 3
_LIVE_API_RETRY_DELAY_SECONDS = 5.0


async def _analyze_incident_react_with_retry(trigger: dict[str, object]) -> IncidentReport:
    """Retries only on a known-transient upstream 503 (Gemini API capacity),
    per the API's own message: "Spikes in demand are usually temporary." A
    real code defect would raise something else and still fail immediately.
    """
    last_error: ServerError | None = None
    for attempt in range(_LIVE_API_RETRIES):
        try:
            return await analyze_incident_react(trigger)
        except ServerError as exc:
            if exc.code != 503:
                raise
            last_error = exc
            if attempt < _LIVE_API_RETRIES - 1:
                await asyncio.sleep(_LIVE_API_RETRY_DELAY_SECONDS)
    assert last_error is not None
    raise last_error


def _registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.scan_skills()
    return registry


def _has_real_api_key() -> bool:
    key = os.getenv("GEMINI_API_KEY")
    return bool(key) and key != "your_gemini_api_key_here"


def test_build_investigative_tools_excludes_terminal_skills() -> None:
    session = InvestigationSession("INC-1")
    tools = build_investigative_tools(_registry(), {}, session)

    names = {tool.name for tool in tools}
    assert names == {"data_drift_analysis", "model_performance_analysis"}
    assert "root_cause_prioritization" not in names
    assert "incident_summary" not in names


def test_tool_name_and_description_match_skill_metadata() -> None:
    registry = _registry()
    session = InvestigationSession("INC-1")
    tools = build_investigative_tools(registry, {}, session)

    for tool in tools:
        meta = registry.get(tool.name)
        assert meta is not None
        assert tool.description == meta.description


async def test_calling_tool_function_directly_executes_skill_and_records_finding() -> None:
    registry = _registry()
    session = InvestigationSession("INC-1")
    skill_parameters = {
        "data_drift_analysis": {
            "reference_dataset_id": "fraud_detection_xgboost",
            "current_dataset_id": "fraud_detection_xgboost",
            "numerical_features": ["transaction_amount"],
            "categorical_features": ["user_zipcode", "device_type"],
            "min_sample_size": 100,
        }
    }
    tools = build_investigative_tools(registry, skill_parameters, session)
    drift_tool = next(t for t in tools if t.name == "data_drift_analysis")

    result = await drift_tool.func()

    assert "confidence_score" in result
    assert session.findings["data_drift_analysis"].confidence_score >= 0.8
    assert "data_drift_analysis" in session.executed_skills
    assert len(session.ledger.entries) > 0
    assert any(
        r.skill_name == "data_drift_analysis" and r.trigger_reason == "llm_selected"
        for r in session.selection_records
    )


async def test_calling_tool_function_records_unavailable_on_bad_params() -> None:
    registry = _registry()
    session = InvestigationSession("INC-1")
    tools = build_investigative_tools(registry, {}, session)
    perf_tool = next(t for t in tools if t.name == "model_performance_analysis")

    result = await perf_tool.func()

    assert "error" in result
    assert "model_performance_analysis" in session.unavailable_skills
    assert "model_performance_analysis" not in session.findings


@pytest.mark.skipif(not _has_real_api_key(), reason="requires a real GEMINI_API_KEY")
async def test_analyze_incident_react_live_end_to_end() -> None:
    trigger: dict[str, object] = {
        "alert_type": "DownstreamAccuracyDrop",
        "severity": "high",
        "affected_system": {
            "system_type": "model_serving",
            "identifier": "Fraud_Detection_XGBoost",
        },
        "detected_at": datetime.now(UTC),
        "source_system": "monitoring",
        "skill_parameters": {
            "data_drift_analysis": {
                "reference_dataset_id": "fraud_detection_xgboost",
                "current_dataset_id": "fraud_detection_xgboost",
                "numerical_features": ["transaction_amount"],
                "categorical_features": ["user_zipcode", "device_type"],
                "min_sample_size": 100,
            },
            "model_performance_analysis": {"predictions_dataset_id": "fraud_detection_xgboost"},
        },
    }

    report = await _analyze_incident_react_with_retry(trigger)

    # Structural assertions only (per .agents/CONTEXT.md: never assert on LLM
    # text/choices) -- the model may legitimately call zero, one, or both
    # investigative tools depending on its own reasoning.
    assert 0.0 <= report.confidence_score <= 1.0
    assert isinstance(report.requires_human_review, bool)
    assert report.incident_id
    assert report.published_at is not None

    investigative_ran = {
        s.skill_name
        for s in report.selected_skills
        if s.trigger_reason == "llm_selected" and not s.excluded
    }
    terminal_ran = {s.skill_name for s in report.selected_skills if s.trigger_reason == "terminal"}

    if investigative_ran:
        assert terminal_ran == {"root_cause_prioritization", "incident_summary"}
        assert report.root_cause_ranking
        assert "# Incident Report:" in report.incident_summary
    else:
        # The model judged nothing relevant -- still a valid, honest outcome.
        assert report.confidence_score == 0.0
