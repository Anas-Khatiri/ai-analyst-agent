# ml-analyst-agent

An autonomous AI Agent platform designed to monitor production data pipelines, machine learning pipelines, and AI systems. It operates out of the loop for passive monitoring and debugging, and incorporates humans in the loop (HITL) for executing critical remediation actions.

## Project Structure

```
ml-analyst-agent/
├── .agents/       # Project customizations and local guardrails (CONTEXT.md)
├── agents/        # ML Analyst Agent: planning/ (skill_selector.py, skill_selection_engine.py),
│                  #   reasoning/ (react_agent.py, the entrypoint), workflow/ (investigation_core.py)
├── api/           # FastAPI application: routers/, schemas/, services/, config.py, main.py
├── domain/        # Business/domain models: Finding, Incident, EvidenceLedger contracts
├── docs/          # Project documentation (specifications, architecture, decisions)
├── evaluation/    # Evaluation datasets (evaluation/datasets/) and runner scripts
├── hooks/         # Pre-commit and static validation hooks
├── infra/         # Cross-cutting infrastructure: skill_registry.py, skill_loader.py,
│                  #   logging_utils.py, security/, tools/ (typed wrappers)
├── services/      # Infrastructure adapters, e.g. services/mock_env/*.py, services/mcp/ (MCP server)
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

3. Set `API_KEY` in `.env` to a secret of your choosing — required to call `POST /incidents` (see "Running the API" below):
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

4. Synchronize development dependencies:
   ```bash
   uv sync --group dev
   ```

5. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

## Running the API

The FastAPI application (`api/main.py`) exposes the ReAct/MCP agent (`agents/reasoning/react_agent.py::analyze_incident_react`) over HTTP.

### Launch it

```bash
uv run uvicorn api.main:app --reload
```

Once it's up, open **http://localhost:8000/docs** for the interactive Swagger UI (or `/redoc` for a read-only version) — both are auto-generated from the request/response schemas, no separate documentation to maintain.

### Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health`, `/ready`, `/live`, `/ping` | Health checks — no agent/LLM involved, no auth required |
| `POST /incidents` | Submits an incident, runs the full investigation, returns the completed `IncidentReport`. **Requires an `X-API-Key` header** matching your `.env`'s `API_KEY` (401 without it, 503 if the server has none configured). **Synchronous** — a real request takes ~8-20s (real Gemini call + a real MCP server subprocess per incident), so don't expect an instant reply |

### Try it with a real request

Four ready-made sample incidents live in `evaluation/datasets/example.jsonl` (one per line) — covering a full success case, a partial-failure case, an "nothing to investigate" escalation case, and a case designed to exercise the `data_drift_analysis` skill specifically:

```bash
sed -n '1p' evaluation/datasets/example.jsonl | curl -X POST http://localhost:8000/incidents \
  -H 'X-API-Key: your-api-key' -H 'Content-Type: application/json' -d @-
```

(swap `1p` for `2p`/`3p`/`4p` to try the other scenarios; in the Swagger UI, click the **"Authorize"** lock icon first to set your API key once, then use "Try it out" on `POST /incidents` as normal)

## Development Commands

See `docs/DEVELOPMENT_GUIDE.md` for full commands and guidelines.
