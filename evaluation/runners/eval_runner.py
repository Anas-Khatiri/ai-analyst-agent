# Evaluation runner for the EDD framework

"""Minimal evaluation runner.

The runner loads a JSONL file where each line is a trigger payload compatible with
`agents.reasoning.react_agent.analyze_incident_react`. For each case it:

1. Starts a trace collector (currently a stub - can be expanded later).
2. Calls the agent asynchronously (a real Gemini call + a real MCP server
   subprocess per case — see agents/reasoning/react_agent.py).
3. Measures latency.
4. Computes basic quality-gate checks using the thresholds defined in
   `evaluation.config`.
5. Aggregates results and prints a concise summary.  The script exits with a
   non-zero status if any case fails a threshold, making it suitable for CI.

Since the agent is LLM-driven, results (which skills get called, latency)
can vary run to run — this harness only asserts structural properties
(latency budget, human-review flag), never which specific skill the model
chose, per .agents/CONTEXT.md §4.
"""

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# Import the agent entrypoint
from agents.reasoning.react_agent import analyze_incident_react
from evaluation.config import (
    CASE_TIMEOUT_SECONDS,
    EVALUATION_PASS_RATE_THRESHOLD,
    MAX_LATENCY_SECONDS,
)
from evaluation.report import generate_report


class EvalResult:
    """Container for a single evaluation case result."""

    def __init__(self, latency: float, passed: bool, details: dict[str, Any]) -> None:
        self.latency = latency
        self.passed = passed
        self.details = details


_TERMINAL_SKILLS = {"root_cause_prioritization", "incident_summary"}

# Substrings identifying a Gemini free-tier quota/rate-limit rejection (both
# the daily cap and the per-minute burst limit surface as RESOURCE_EXHAUSTED
# with a 429 status) -- distinct from a real agent/skill bug, and excluded
# from the pass-rate gate below rather than counted as a failure.
_QUOTA_MARKERS = ("RESOURCE_EXHAUSTED", "429")


def _is_quota_exhausted(error_message: str) -> bool:
    return any(marker in error_message for marker in _QUOTA_MARKERS)


async def evaluate_one(payload: dict[str, Any]) -> EvalResult:
    """Run the agent on a single payload and evaluate it against structural
    checks -- never against which specific skill the model chose to call,
    per .agents/CONTEXT.md §4's rule against asserting on LLM output.

    1. Crash containment: an exception (Gemini/MCP failure, malformed
       payload) fails this one case with the error captured, instead of
       taking down the whole evaluation run for every other case too.
    2. Hang containment: a case that neither finishes nor raises within
       CASE_TIMEOUT_SECONDS (a stuck MCP subprocess, a network stall) is
       cancelled and recorded as a timeout, rather than blocking every
       remaining case -- and the whole CI job -- indefinitely.
    3. Latency budget.
    4. Confidence/root-cause consistency: a report that doesn't require
       human review must actually point at a root cause -- "confidently
       empty" is a real bug class, not a valid outcome.
    5. Terminal-wave completeness: root_cause_prioritization and
       incident_summary must both have run, since combination is required
       to stay deterministic regardless of selection mode (ADR-004 §3.3,
       ADR-006). A case that legitimately found nothing to investigate
       (requires_human_review=True) is exempt from checks 4 and 5 -- see
       evaluation/datasets/example.jsonl's escalation-case sample.
    """
    start = time.time()
    try:
        report = await asyncio.wait_for(
            analyze_incident_react(payload), timeout=CASE_TIMEOUT_SECONDS
        )
    except TimeoutError:
        latency = time.time() - start
        return EvalResult(
            latency=latency,
            passed=False,
            details={
                "latency": latency,
                "crash": f"Case exceeded the {CASE_TIMEOUT_SECONDS}s hang-containment timeout",
            },
        )
    except Exception as exc:
        latency = time.time() - start
        error_message = str(exc)
        crash_details: dict[str, Any] = {"latency": latency, "crash": error_message}
        if _is_quota_exhausted(error_message):
            crash_details["quota_exhausted"] = True
        return EvalResult(latency=latency, passed=False, details=crash_details)
    latency = time.time() - start

    passed = True
    details: dict[str, Any] = {
        "latency": latency,
        "requires_human_review": report.requires_human_review,
    }

    if latency > MAX_LATENCY_SECONDS:
        passed = False
        details["latency_fail"] = f"{latency:.2f}s > {MAX_LATENCY_SECONDS}s"

    if report.requires_human_review:
        details["human_review"] = "Report flagged for human review (may be a valid escalation)"
    else:
        if not report.root_cause_ranking:
            passed = False
            details["confidence_consistency_fail"] = (
                "Report claims confidence but root_cause_ranking is empty"
            )

        terminal_ran = {
            s.skill_name for s in report.selected_skills if s.trigger_reason == "terminal"
        }
        if terminal_ran != _TERMINAL_SKILLS:
            passed = False
            details["terminal_wave_fail"] = (
                f"Expected both terminal skills to run, got: {sorted(terminal_ran)}"
            )

    return EvalResult(latency=latency, passed=passed, details=details)


async def run_dataset(dataset_path: Path) -> list[EvalResult]:
    """Iterate over a JSONL dataset and evaluate each entry."""
    results: list[EvalResult] = []
    async for line in _async_file_reader(dataset_path):
        payload = json.loads(line)
        result = await evaluate_one(payload)
        results.append(result)
    return results


async def _async_file_reader(path: Path) -> AsyncIterator[str]:
    """Yield lines from a file asynchronously (simple wrapper)."""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield line.strip()


def summarize(results: list[EvalResult]) -> None:
    total = len(results)
    quota_exhausted = [r for r in results if r.details.get("quota_exhausted")]
    gated = [r for r in results if not r.details.get("quota_exhausted")]

    print("=== Evaluation Summary ===")
    print(f"Cases evaluated : {total}")
    if quota_exhausted:
        print(
            f"Excluded (quota/rate-limit hit): {len(quota_exhausted)} -- Gemini free-tier "
            "limit, not a code regression; excluded from the pass-rate gate below"
        )

    if not gated:
        print("No cases produced a real result (all hit quota/rate limits) -- inconclusive,")
        print("not treated as pass or fail. Retry once quota resets.")
        return

    passed = sum(r.passed for r in gated)
    pass_rate = passed / len(gated)
    avg_latency = sum(r.latency for r in gated) / len(gated)
    print(f"Pass rate      : {pass_rate:.2%} (threshold {EVALUATION_PASS_RATE_THRESHOLD:.2%})")
    print(f"Avg latency    : {avg_latency:.2f}s (threshold {MAX_LATENCY_SECONDS:.2f}s)")
    if pass_rate < EVALUATION_PASS_RATE_THRESHOLD:
        sys.exit(1)
    if avg_latency > MAX_LATENCY_SECONDS:
        sys.exit(1)
    # Exit 0 if everything is within thresholds.


if __name__ == "__main__":
    # Expect a path to a JSONL dataset as the first argument.
    if len(sys.argv) != 2:
        print("Usage: python -m evaluation.runners.eval_runner <dataset.jsonl>")
        sys.exit(2)
    dataset_file = Path(sys.argv[1])
    if not dataset_file.is_file():
        print(f"Dataset file not found: {dataset_file}")
        sys.exit(2)
    results = asyncio.run(run_dataset(dataset_file))
    # Generate a detailed HTML (and JSON) report for CI/artifact consumption
    from pathlib import Path

    report_path = Path("reports/evaluation_report.html")
    generate_report(results, report_path)
    summarize(results)
