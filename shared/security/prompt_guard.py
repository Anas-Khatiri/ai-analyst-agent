import re

from .exceptions import SecurityError

# Simple blacklist patterns for demonstration. Extend as needed.
_BLACKLIST_PATTERNS = [
    re.compile(r"ignore\s+safety", re.IGNORECASE),
    re.compile(r"ignore", re.IGNORECASE),
]


def check_prompt(prompt: str) -> None:
    """Validate a user prompt against blacklisted patterns.

    Raises:
        SecurityError: If the prompt contains any blacklisted content.
    """
    for pattern in _BLACKLIST_PATTERNS:
        if pattern.search(prompt):
            raise SecurityError(f"Prompt contains disallowed content: '{pattern.pattern}'")
