# ml-analyst-agent

An autonomous AI Agent platform designed to monitor production data pipelines, machine learning pipelines, and AI systems. It operates out of the loop for passive monitoring and debugging, and incorporates humans in the loop (HITL) for executing critical remediation actions.

## Project Structure

```
ml-analyst-agent/
├── .agents/       # Project customizations and local guardrails (CONTEXT.md)
├── agents/        # ML Analyst Agent: react_agent.py (entrypoint), investigation_core.py, skill_selection_engine.py
├── api/           # FastAPI application (not yet implemented)
├── docs/          # Project documentation (specifications, architecture, decisions)
├── eval/          # Evaluation datasets and scripts
├── hooks/         # Pre-commit and static validation hooks
├── services/      # Infrastructure adapters, e.g. services/mock_env/*.py
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

## Development Commands

See `docs/DEVELOPMENT_GUIDE.md` for full commands and guidelines.
