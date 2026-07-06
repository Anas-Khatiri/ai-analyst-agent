# Configuration for the Evaluation Driven Development (EDD) framework
#
# Only thresholds actually enforced by evaluation/runners/eval_runner.py live
# here. An earlier revision had 12 additional constants (LLM-as-judge
# settings, golden-dataset paths, qualitative score thresholds) that were
# never read by any code -- the LLM-as-judge scoring system they anticipated
# was never built. Removed rather than left as decoration; re-add alongside
# the code that actually uses them if that system gets built.

# The agent's only entrypoint (agents/react_agent.py::analyze_incident_react)
# spawns a real MCP server subprocess and makes a real Gemini call per
# incident, per ADR-006-remove-deterministic-mode.md -- 3s (the old
# deterministic-path budget) is unrealistic; ~8s was observed for a live
# end-to-end run in this repo's test suite.
MAX_LATENCY_SECONDS = 20.0  # <= 20 seconds

# Hard backstop against a genuinely hung call (stuck MCP subprocess, network
# stall) -- distinct from MAX_LATENCY_SECONDS, which just flags "too slow but
# it did finish." Generous on purpose so it never trips on a legitimately
# slow-but-working case, only one that's truly stuck.
CASE_TIMEOUT_SECONDS = 120.0

EVALUATION_PASS_RATE_THRESHOLD = 0.98  # 98% of cases must pass every check below
