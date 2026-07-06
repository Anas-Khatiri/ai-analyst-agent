# ml-analyst-agent

An autonomous AI Agent platform designed to monitor production data pipelines, machine learning pipelines, and AI systems. It operates out of the loop for passive monitoring and debugging, and incorporates humans in the loop (HITL) for executing critical remediation actions.

## Project Structure

```
ml-analyst-agent/
├── .agents/       # Project customizations and local guardrails (CONTEXT.md)
├── agents/        # ML Analyst Agent: react_agent.py (entrypoint), investigation_core.py, skill_selection_engine.py
├── api/           # FastAPI application: routers/, schemas/, services/, config.py, main.py
├── docs/          # Project documentation (specifications, architecture, decisions)
├── evaluation/    # Evaluation datasets (evaluation/datasets/) and runner scripts
├── hooks/         # Pre-commit and static validation hooks
├── services/      # Infrastructure adapters, e.g. services/mock_env/*.py, services/mcp/ (MCP server)
├── shared/        # Cross-cutting code: schemas/ (Finding, incident, evidence ledger contracts),
│                  #   tools/ (typed wrappers), skill_registry.py, skill_loader.py
├── skills/        # Skill specs (SKILL.md) plus each skill's scripts/ implementation
├── tests/         # Unit and integration tests
├── .venv/         # Isolated virtual environment
├── pyproject.toml # Dependency definitions
└── README.md      # Project overview
```

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Gemini API Key (set in `.env`)

### Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Populate the `GEMINI_API_KEY` in `.env` with your API key.

3. Synchronize development dependencies:
   ```bash
   uv sync --group dev
   ```

4. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

## Running the API

The FastAPI application (`api/main.py`) exposes the ReAct/MCP agent (`agents/react_agent.py::analyze_incident_react`) over HTTP.

### Launch it

```bash
uv run uvicorn api.main:app --reload
```

Once it's up, open **http://localhost:8000/docs** for the interactive Swagger UI (or `/redoc` for a read-only version) — both are auto-generated from the request/response schemas, no separate documentation to maintain.

### Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health`, `/ready`, `/live`, `/ping` | Health checks — no agent/LLM involved |
| `POST /incidents` | Submits an incident, runs the full investigation, returns the completed `IncidentReport`. **Synchronous** — a real request takes ~8-20s (real Gemini call + a real MCP server subprocess per incident), so don't expect an instant reply |

### Try it with a real request

Four ready-made sample incidents live in `evaluation/datasets/example.jsonl` (one per line) — covering a full success case, a partial-failure case, an "nothing to investigate" escalation case, and a case designed to exercise the `data_drift_analysis` skill specifically:

```bash
sed -n '1p' evaluation/datasets/example.jsonl | curl -X POST http://localhost:8000/incidents \
  -H 'Content-Type: application/json' -d @-
```

(swap `1p` for `2p`/`3p`/`4p` to try the other scenarios, or paste a line into the Swagger UI's "Try it out" box for `POST /incidents`)

## Development Commands

See `docs/DEVELOPMENT_GUIDE.md` for full commands and guidelines.
