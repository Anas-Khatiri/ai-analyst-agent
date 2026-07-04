.PHONY: install run test lint format clean

# Standard install using uv package manager
install:
	uv sync --group dev

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

# Clean cache directories
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
