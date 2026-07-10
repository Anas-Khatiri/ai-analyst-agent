"""Loads .env before test collection so live-gated tests (skipif on a real
GEMINI_API_KEY) actually run locally instead of silently skipping.

Scoped to local `uv run pytest` only: the pre-commit hook explicitly runs
`env -u GEMINI_API_KEY uv run pytest` and CI's ci-cd.yml test job has no
.env file present, so this has no effect on either -- both stay free, fast,
and deterministic as documented there. evaluation.yml is the workflow that
exercises the real agent against a real Gemini key.
"""

from dotenv import load_dotenv

load_dotenv()
