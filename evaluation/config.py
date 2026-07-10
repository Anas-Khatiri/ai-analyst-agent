# Configuration for the Evaluation Driven Development (EDD) framework
#
# Only thresholds actually enforced by evaluation/runners/eval_runner.py live
# here. An earlier revision had 12 additional constants (LLM-as-judge
# settings, golden-dataset paths, qualitative score thresholds) that were
# never read by any code -- the LLM-as-judge scoring system they anticipated
# was never built. Removed rather than left as decoration; re-add alongside
# the code that actually uses them if that system gets built.

# The agent's only entrypoint (agents/reasoning/react_agent.py::analyze_incident_react)
# spawns a real MCP server subprocess and makes a real Gemini call per
# incident, per ADR-006-remove-deterministic-mode.md -- 3s (the old
# deterministic-path budget) is unrealistic; ~8s was observed for a live
# end-to-end run in this repo's test suite.
#
# Per ADR-007-skill-selection-gate.md, a second sequential real LLM call
# (agents/planning/skill_selector.py's metadata-only structured-output selection)
# now runs before the MCP subprocess is even spawned, on top of the
# original ReAct call this 8s figure was based on. A clean two-call
# measurement wasn't obtainable when this was raised: Gemini was under
# sustained transient overload (repeated 503 "high demand" responses) in
# this repo's test environment at the time, which inflated one live run
# past 500s via the SDK's own internal retry/backoff -- not representative
# of normal latency, so that number isn't used here. This budget is instead
# a reasoned (not measured) increase over the original 20.0s, generous the
# same way that figure was generous over the theoretical single-call floor;
# revisit with a real measurement once Gemini capacity is stable.
MAX_LATENCY_SECONDS = 30.0  # <= 30 seconds

# Hard backstop against a genuinely hung call (stuck MCP subprocess, network
# stall) -- distinct from MAX_LATENCY_SECONDS, which just flags "too slow but
# it did finish." Generous on purpose so it never trips on a legitimately
# slow-but-working case, only one that's truly stuck.
CASE_TIMEOUT_SECONDS = 120.0

EVALUATION_PASS_RATE_THRESHOLD = 0.98  # 98% of cases must pass every check below
