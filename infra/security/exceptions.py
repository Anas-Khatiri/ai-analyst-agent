"""Exceptions used by the security package."""


class SecurityError(RuntimeError):
    """Raised when a security rule is violated (prompt injection, tool not allowed, etc.)."""


class ValidationError(RuntimeError):
    """Raised when input validation via Pydantic fails."""
