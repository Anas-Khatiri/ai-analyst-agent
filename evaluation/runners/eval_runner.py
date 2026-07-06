# Evaluation runner for the EDD framework

"""Minimal evaluation runner.

The runner loads a JSONL file where each line is a trigger payload compatible with
`agents.react_agent.analyze_incident_react`. For each case it:

1. Starts a trace collector (currently a stub - can be expanded later).
2. Calls the agent asynchronously (a real Gemini call + a real MCP server
   subprocess per case — see agents/react_agent.py).
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
from agents.react_agent import analyze_incident_react
from evaluation.config import (
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


async def evaluate_one(payload: dict[str, Any]) -> EvalResult:
    """Run the agent on a single payload and evaluate thresholds.

    The function is deliberately simple - it only checks latency and whether the
    report requires human review (a proxy for routing/analysis quality). More
    sophisticated checks (e.g., hallucination detection, schema validation) can be
    added later.
    """
    start = time.time()
    report = await analyze_incident_react(payload)
    latency = time.time() - start

    # Basic quality checks - expand as needed.
    passed = True
    details: dict[str, Any] = {
        "latency": latency,
        "requires_human_review": report.requires_human_review,
    }

    if latency > MAX_LATENCY_SECONDS:
        passed = False
        details["latency_fail"] = f"{latency:.2f}s > {MAX_LATENCY_SECONDS}s"

    if report.requires_human_review:
        passed = False
        details["human_review_fail"] = "Report flagged for human review"

    # Placeholder for other metric checks - they can be added here using the
    # thresholds imported from `evaluation.config`.

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
    passed = sum(r.passed for r in results)
    pass_rate = passed / total if total else 0.0
    avg_latency = sum(r.latency for r in results) / total if total else 0.0
    print("=== Evaluation Summary ===")
    print(f"Cases evaluated : {total}")
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
