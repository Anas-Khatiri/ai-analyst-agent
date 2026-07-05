from __future__ import annotations

from datetime import UTC, datetime

from agents.ml_analyst_agent import analyze_incident

_FRAUD_TRIGGER: dict[str, object] = {
    "alert_type": "DownstreamAccuracyDrop",
    "severity": "high",
    "affected_system": {"system_type": "model_serving", "identifier": "Fraud_Detection_XGBoost"},
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


async def test_analyze_incident_full_dynamic_pipeline_matches_documented_scenario() -> None:
    report = await analyze_incident(_FRAUD_TRIGGER)

    assert report.confidence_score >= 0.8
    assert not report.requires_human_review
    assert not report.partial_investigation

    causes = [c.cause for c in report.root_cause_ranking]
    assert any("user_zipcode" in cause for cause in causes)
    assert any("transaction_amount" in cause for cause in causes)

    assert "# Incident Report:" in report.incident_summary
    assert len(report.selected_skills) >= 4
    executed = {s.skill_name for s in report.selected_skills if not s.excluded}
    assert executed == {
        "data_drift_analysis",
        "model_performance_analysis",
        "root_cause_prioritization",
        "incident_summary",
    }
    assert len(report.supporting_evidence) > 0


async def test_analyze_incident_unknown_alert_escalates_without_crashing() -> None:
    trigger: dict[str, object] = {
        "alert_type": "SomeUnknownAlertType",
        "severity": "medium",
        "affected_system": {"system_type": "model_serving", "identifier": "Unknown_Service"},
        "detected_at": datetime.now(UTC),
    }
    report = await analyze_incident(trigger)

    assert report.requires_human_review
    assert report.confidence_score == 0.0
    assert report.selected_skills == []
    assert report.findings == {}


async def test_analyze_incident_partial_when_investigative_skill_params_missing() -> None:
    trigger: dict[str, object] = {
        "alert_type": "DownstreamAccuracyDrop",
        "severity": "high",
        "affected_system": {
            "system_type": "model_serving",
            "identifier": "Fraud_Detection_XGBoost",
        },
        "detected_at": datetime.now(UTC),
        "skill_parameters": {
            "data_drift_analysis": _FRAUD_TRIGGER["skill_parameters"]["data_drift_analysis"],  # type: ignore[index]
        },
    }
    report = await analyze_incident(trigger)

    executed = {s.skill_name for s in report.selected_skills if not s.excluded}
    assert "model_performance_analysis" not in executed
    excluded_names = {s.skill_name for s in report.selected_skills if s.excluded}
    assert "model_performance_analysis" in excluded_names
    # Still reaches a diagnosis from the one skill that did run, through ranking + reporting.
    assert "root_cause_prioritization" in executed
    assert "incident_summary" in executed
