#!/usr/bin/env bash
# Pre-push hook wrapper around pytest.
#
# The project is still in its specification phase and `tests/` is
# intentionally empty in places — pytest's exit code 5 ("no tests collected")
# must not block a push in that state. Any other non-zero exit (a real
# failure or error) still blocks, unchanged.
set -uo pipefail

uv run pytest tests/ -q
exit_code=$?

if [ "$exit_code" -eq 0 ] || [ "$exit_code" -eq 5 ]; then
  exit 0
fi
exit "$exit_code"
