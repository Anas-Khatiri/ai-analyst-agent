# Development Guide

This guide covers day-to-day development commands and the quality gates every change must pass before landing, per [`.agents/CONTEXT.md`](../.agents/CONTEXT.md).

## Setup

```bash
cp .env.example .env          # then populate GEMINI_API_KEY
make install                   # uv sync --group dev  +  uv run pre-commit install
```

`make install` does two things: it syncs the dev dependency group with `uv`, and it activates the git pre-commit hooks (`.pre-commit-config.yaml`) so every subsequent commit is checked automatically. If you already ran `uv sync` manually and just need the hooks activated, run `make hooks` instead.

Verify the environment is fully wired up (Google ADK import + Gemini API reachability):

```bash
uv run python scripts/verify_setup.py
```

## Everyday Commands

| Command | Purpose |
|---|---|
| `make run` | Start the FastAPI backend (`api.main:app`) with reload. |
| `make test` | Run the pytest suite (`tests/`). |
| `make lint` | Run Ruff check + Mypy across the repo — the same checks pre-commit runs, useful to check before staging. |
| `make format` | Auto-format the codebase with Ruff. |
| `make security` | Run the custom Semgrep ruleset (no raw shell execution / no eval-exec) standalone. |
| `make hooks` | (Re-)install the pre-commit hooks and run them against every file — use after pulling a `.pre-commit-config.yaml` change, or to sanity-check the whole repo. |
| `make clean` | Remove `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`. |

## Pre-Commit Hooks

Every commit is checked automatically once `make install` (or `make hooks`) has run once. The full hook list, and which coding standard each one enforces, is documented in [`.agents/CONTEXT.md §7`](../.agents/CONTEXT.md). In short: file hygiene, secret scanning (`detect-secrets`), Ruff lint/format, Mypy strict typing, and a custom Semgrep rule blocking raw shell execution (`subprocess`, `os.system`, `eval`/`exec`) in agent/skill runtime code. The pytest suite runs on `git push` rather than on every commit, since it is slower than the lint pass.

**If a hook fails**: treat it as a real defect, not an obstacle — see the Pre-Commit Remediation Loop in [`.agents/CONTEXT.md §2.4`](../.agents/CONTEXT.md#24-pre-commit-remediation-loop). Fix the underlying issue and re-commit; never bypass a failing hook with `--no-verify`. Some hooks (`ruff-format`, `trailing-whitespace`, `end-of-file-fixer`) auto-fix and re-stage the offending files — in that case, just `git add` the modified files and commit again.

**Triaging a new `detect-secrets` finding**: if the hook flags something that is genuinely not a secret (e.g., a documentation placeholder or an example value), update the baseline and audit it explicitly rather than deleting the finding by hand:

```bash
uv run --with detect-secrets detect-secrets scan --baseline .secrets.baseline
uv run --with detect-secrets detect-secrets audit .secrets.baseline
```

A finding that *is* a real secret must never be baselined — remove the secret from the code, rotate it if it was ever committed, and re-run the scan.

## Code Standards Reference

The authoritative rules for typing, tool schemas, security boundaries, telemetry, testing, and skill/agent architecture patterns live in [`.agents/CONTEXT.md`](../.agents/CONTEXT.md) — read it before implementing a new agent, tool, or skill. The behavioral specifications for the platform's components live under [`docs/agents/`](agents/) and [`docs/specifications/`](specifications/).
