# Configuration for the Evaluation Driven Development (EDD) framework

from pathlib import Path

# LLM provider for judge component
LLM_PROVIDER = "gemini"  # options: gemini, openai, cohere

# LLM API key environment variable name
LLM_API_KEY_ENV = "LLM_API_KEY"  # pragma: allowlist secret

# Quality gate thresholds (user-specified)
ROUTING_ACCURACY_THRESHOLD = 0.95  # 95%
DATA_QUALITY_DETECTION_THRESHOLD = 0.96  # 96%
ML_ANALYSIS_QUALITY_THRESHOLD = 4.5  # out of 5
ROOT_CAUSE_QUALITY_THRESHOLD = 0.92  # 92%
RECOMMENDATION_QUALITY_THRESHOLD = 4.5  # out of 5
SECURITY_CONTAINMENT_THRESHOLD = 1.0  # 100%
SCHEMA_VALIDATION_THRESHOLD = 1.0  # 100%
EVALUATION_PASS_RATE_THRESHOLD = 0.98  # 98%
HALLUCINATION_RATE_MAX = 0.02  # 2%
# The agent's only entrypoint (agents/react_agent.py::analyze_incident_react)
# spawns a real MCP server subprocess and makes a real Gemini call per
# incident, per ADR-006-remove-deterministic-mode.md -- 3s (the old
# deterministic-path budget) is unrealistic; ~8s was observed for a live
# end-to-end run in this repo's test suite.
MAX_LATENCY_SECONDS = 20.0  # <= 20 seconds
ALLOW_SECURITY_LEAKS = False

# Dataset paths (relative to this package)
DATASET_DIR = "datasets"
GOLDEN_CASES_DIR = "golden_cases"
TRACES_DIR = "traces"

# Mock judge mode (use when API key not available)
MOCK_JUDGE = True

# Duplicate import removed; Path already imported at top

BASE_PATH = Path(__file__).parent
DATASET_PATH = BASE_PATH / DATASET_DIR
GOLDEN_PATH = BASE_PATH / GOLDEN_CASES_DIR
TRACES_PATH = BASE_PATH / TRACES_DIR
