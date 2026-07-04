.PHONY: install hooks run test lint format security clean

# Standard install using uv package manager, plus git hook activation
install:
	uv sync --group dev
	uv run pre-commit install

# (Re-)install/update the pre-commit git hooks without a full dependency sync
hooks:
	uv run pre-commit install
	uv run pre-commit run --all-files

# Runs the FastAPI backend service
run:
	uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Runs the pytest suite
test:
	uv run pytest tests/

# Runs static code analysis (Ruff + Mypy)
lint:
	uv run ruff check .
	uv run mypy .

# Runs Ruff formatting
format:
	uv run ruff format .

# Runs the Semgrep security ruleset (no raw shell execution / no eval-exec)
security:
	uv run semgrep scan --config hooks/semgrep/no_raw_shell_exec.yaml

# Clean cache directories
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
