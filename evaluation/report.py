from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evaluation.runners.eval_runner import EvalResult

# Import the EvalResult type from the runner (to avoid circular imports, we import lazily in generate_report)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8'>
  <title>Evaluation Report</title>
  <style>
    body {font-family: Arial, sans-serif; margin: 2rem;}
    table {border-collapse: collapse; width: 100%;}
    th, td {border: 1px solid #ddd; padding: 8px;}
    th {background-color: #f2f2f2;}
    .pass {background-color: #d4edda;}
    .fail {background-color: #f8d7da;}
  </style>
</head>
<body>
  <h1>Evaluation Report</h1>
  <p>Total cases: {total}</p>
  <p>Pass rate: {pass_rate:.2%}</p>
  <p>Average latency: {avg_latency:.2f}s</p>
  <table>
    <thead>
      <tr><th>#</th><th>Latency (s)</th><th>Status</th><th>Details</th></tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>
</body>
</html>"""


def _format_details(details: dict[str, Any]) -> str:
    """Pretty‑print details as HTML.

    Simple implementation: JSON‑encode and replace new‑lines with <br>.
    """
    return json.dumps(details, indent=2).replace("\n", "<br>").replace(" ", "&nbsp;")


def generate_report(results: list[EvalResult], output_path: Path) -> None:
    """Generate an HTML (and JSON) report from a list of ``EvalResult``.

    The function writes ``output_path`` (an ``.html`` file) and also a JSON
    representation ``output_path.with_suffix('.json')`` for downstream tooling.

    ``EvalResult`` is defined in ``evaluation.runners.eval_runner`` – we import it
    lazily to avoid circular imports.
    """
    # Lazy import to sidestep circular dependency

    total = len(results)
    passed = sum(r.passed for r in results)
    pass_rate = passed / total if total else 0.0
    avg_latency = sum(r.latency for r in results) / total if total else 0.0

    rows = []
    for idx, res in enumerate(results, start=1):
        status_cls = "pass" if res.passed else "fail"
        rows.append(
            f"      <tr class='{status_cls}'><td>{idx}</td><td>{res.latency:.2f}</td><td>{'PASS' if res.passed else 'FAIL'}</td><td>{_format_details(res.details)}</td></tr>"
        )
    rows_str = "\n".join(rows)

    html_content = HTML_TEMPLATE.format(
        total=total,
        pass_rate=pass_rate,
        avg_latency=avg_latency,
        rows=rows_str,
    )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")

    # Write JSON version
    json_path = output_path.with_suffix(".json")
    json_data = [
        {
            "latency": r.latency,
            "passed": r.passed,
            "details": r.details,
        }
        for r in results
    ]
    json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
