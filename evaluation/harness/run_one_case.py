import asyncio
import time
from datetime import UTC, datetime

from agents.react_agent import analyze_incident_react
from evaluation.config import MAX_LATENCY_SECONDS


async def main() -> None:
    """Run a single incident through the agent and assert core thresholds.

    This harness makes a real Gemini call and spawns a real MCP server
    subprocess per run (agents/react_agent.py) — it is no longer a free,
    deterministic check, since Mode 1 (the rule-based deterministic agent)
    was removed per ADR-006-remove-deterministic-mode.md. Results can vary
    run to run depending on which investigative skill(s) the model chooses
    to call. The trigger below mirrors the fraud-detection fixture used in
    tests/agents/test_react_agent.py's live end-to-end test, giving the
    model real signal to act on (a bare/unrecognizable alert type would
    give it nothing to call, failing the review-flag assertion trivially).
    """
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
    start = time.time()
    report = await analyze_incident_react(trigger)
    latency = time.time() - start

    # Basic sanity checks against configured thresholds.
    assert latency <= MAX_LATENCY_SECONDS, f"Latency {latency:.2f}s exceeds {MAX_LATENCY_SECONDS}s"
    assert not report.requires_human_review, "Human review required - fails quality gate"
    print(
        "✅ Harness execution succeeded",
        {"latency": latency, "requires_human_review": report.requires_human_review},
    )


if __name__ == "__main__":
    asyncio.run(main())
