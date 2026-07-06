# ==============================================================================
# Build Stage: Installs dependencies using uv
# ==============================================================================
FROM python:3.11-slim AS builder

# Prevent python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:0.9.0 /uv /uvx /bin/

# Copy only the files needed for dependency resolution
COPY pyproject.toml uv.lock ./

# Synchronize dependencies (excluding dev dependencies for production)
RUN --mount=type=cache,target=/root/.cache/uv \
    /bin/uv sync --frozen --no-dev --no-install-project

# ==============================================================================
# Final Runtime Stage: Thin image containing only application and dependencies
# ==============================================================================
FROM python:3.11-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Create a non-privileged system user for running the application securely
RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid 10001 --shell /bin/bash --create-home appuser

# Copy virtual environment from builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy all project modules and directories (excluding gitignored files)
COPY agents/ agents/
COPY skills/ skills/
COPY shared/ shared/
COPY services/ services/
COPY api/ api/

# Adjust permissions so the non-privileged user owns the app directory
RUN chown -R appuser:appgroup /app

# Switch to the non-privileged user
USER appuser

# Expose FastAPI service port
EXPOSE 8000

# Run the backend FastAPI application using uvicorn
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
