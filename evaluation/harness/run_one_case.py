import asyncio
import time

from agents.ml_analyst_agent import analyze_incident
from evaluation.config import MAX_LATENCY_SECONDS


async def main() -> None:
    """Run a single minimal incident through the agent and assert core thresholds.

    This harness serves as a fast, deterministic CI check. It does not invoke the
    LLM-as-judge (MOCK_JUDGE is assumed). The trigger below is deliberately minimal
    and matches the schema expected by `analyze_incident`.
    """
    # Minimal trigger payload.
    trigger: dict[str, object] = {
        "alert_type": "test_alert",
        "severity": "high",
        "affected_system": {"identifier": "test_system"},
        "detected_at": "2023-01-01T00:00:00Z",
        "skill_parameters": {},
    }
    start = time.time()
    report = await analyze_incident(trigger)
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
