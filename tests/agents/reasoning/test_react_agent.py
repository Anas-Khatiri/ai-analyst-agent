from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from google.genai.errors import ServerError

from agents.reasoning.react_agent import (
    _extract_tool_payload,
    _record_tool_observation,
    analyze_incident_react,
)
from agents.workflow.investigation_core import InvestigationSession
from domain.incident import IncidentReport

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


def _has_real_api_key() -> bool:
    key = os.getenv("GEMINI_API_KEY")
    return bool(key) and key != "your_gemini_api_key_here"


def test_extract_tool_payload_from_structured_content() -> None:
    mcp_response = {
        "content": [{"type": "text", "text": '{\n  "confidence_score": 0.9\n}'}],
        "structuredContent": {"confidence_score": 0.9},
        "isError": False,
    }

    assert _extract_tool_payload(mcp_response) == {"confidence_score": 0.9}


def test_extract_tool_payload_falls_back_to_content_text() -> None:
    mcp_response = {
        "content": [{"type": "text", "text": '{"confidence_score": 0.5}'}],
        "isError": False,
    }

    assert _extract_tool_payload(mcp_response) == {"confidence_score": 0.5}


def test_extract_tool_payload_from_is_error() -> None:
    mcp_response = {
        "content": [{"type": "text", "text": "boom"}],
        "isError": True,
    }

    assert _extract_tool_payload(mcp_response) == {"error": "boom"}


def test_record_tool_observation_records_finding_and_selection_record() -> None:
    session = InvestigationSession("INC-1")
    payload = {
        "investigation_summary": "drift detected",
        "evidence": [
            {
                "evidence_id": "drift-1",
                "subject": "transaction_amount",
                "metric": "psi",
                "value": 0.4,
                "baseline": 0.1,
                "time_window": {
                    "start": "2026-01-01T00:00:00Z",
                    "end": "2026-01-02T00:00:00Z",
                },
                "source_skill": "data_drift_analysis",
            }
        ],
        "possible_root_causes": [],
        "confidence_score": 0.9,
        "recommended_actions": [],
        "preventive_actions": [],
        "limitations": [],
    }

    _record_tool_observation("data_drift_analysis", payload, session)

    assert session.findings["data_drift_analysis"].confidence_score == 0.9
    assert "data_drift_analysis" in session.executed_skills
    assert len(session.ledger.entries) > 0
    assert any(
        r.skill_name == "data_drift_analysis" and r.trigger_reason == "llm_selected"
        for r in session.selection_records
    )


def test_record_tool_observation_records_unavailable_on_error_payload() -> None:
    session = InvestigationSession("INC-1")

    _record_tool_observation("model_performance_analysis", {"error": "boom"}, session)

    assert session.unavailable_skills["model_performance_analysis"] == "boom"
    assert "model_performance_analysis" not in session.findings
    failed_record = next(
        r for r in session.selection_records if r.skill_name == "model_performance_analysis"
    )
    assert failed_record.excluded is True
    assert failed_record.exclusion_reason == "boom"
    assert failed_record.trigger_reason == "llm_selected"


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
