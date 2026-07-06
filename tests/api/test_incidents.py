from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api.config import APISettings, get_settings
from api.main import app
from shared.schemas.incident import IncidentReport

_VALID_TRIGGER: dict[str, object] = {
    "alert_type": "DownstreamAccuracyDrop",
    "severity": "high",
    "affected_system": {
        "system_type": "model_serving",
        "identifier": "Fraud_Detection_XGBoost",
    },
    "detected_at": datetime.now(UTC).isoformat(),
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


def _fake_report() -> IncidentReport:
    return IncidentReport(
        incident_id="INC-TEST-1",
        incident_summary="# Incident Report: mocked",
        confidence_score=0.9,
        published_at=datetime.now(UTC),
    )


def _has_real_api_key() -> bool:
    key = os.getenv("GEMINI_API_KEY")
    return bool(key) and key != "your_gemini_api_key_here"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_incident_returns_agent_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_analyze(
        trigger: dict[str, object], model: str, max_tool_calls: int
    ) -> IncidentReport:
        return _fake_report()

    monkeypatch.setattr("api.services.incident_service.analyze_incident_react", _fake_analyze)

    response = client.post("/incidents", json=_VALID_TRIGGER)

    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] == "INC-TEST-1"
    assert body["confidence_score"] == 0.9


def test_create_incident_missing_required_field_returns_422(client: TestClient) -> None:
    invalid_trigger = dict(_VALID_TRIGGER)
    del invalid_trigger["affected_system"]

    response = client.post("/incidents", json=invalid_trigger)

    assert response.status_code == 422


def test_create_incident_agent_failure_returns_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raising_analyze(
        trigger: dict[str, object], model: str, max_tool_calls: int
    ) -> IncidentReport:
        raise RuntimeError("boom: internal secret detail")

    monkeypatch.setattr("api.services.incident_service.analyze_incident_react", _raising_analyze)

    response = client.post("/incidents", json=_VALID_TRIGGER)

    assert response.status_code == 502
    assert "boom" not in response.text


def test_create_incident_timeout_returns_504(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _slow_analyze(
        trigger: dict[str, object], model: str, max_tool_calls: int
    ) -> IncidentReport:
        await asyncio.sleep(0.2)
        return _fake_report()

    monkeypatch.setattr("api.services.incident_service.analyze_incident_react", _slow_analyze)
    app.dependency_overrides[get_settings] = lambda: APISettings(request_timeout_seconds=0.05)

    response = client.post("/incidents", json=_VALID_TRIGGER)

    assert response.status_code == 504


@pytest.mark.skipif(not _has_real_api_key(), reason="requires a real GEMINI_API_KEY")
def test_create_incident_live_end_to_end(client: TestClient) -> None:
    response = client.post("/incidents", json=_VALID_TRIGGER)

    assert response.status_code == 200
    body = response.json()
    assert 0.0 <= body["confidence_score"] <= 1.0
    assert isinstance(body["requires_human_review"], bool)
    assert body["incident_id"]
