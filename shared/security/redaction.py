import re
from re import Pattern

# Regex patterns for common PII types
_EMAIL_RE: Pattern[str] = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE: Pattern[str] = re.compile(r"\+?\d[\d\-\s\(\)]{7,}\d")
_IP_RE: Pattern[str] = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_APIKEY_RE: Pattern[str] = re.compile(
    r"(?i)\b(api[_-]?key|token|secret)[=:]?\s*"
    r"[A-Za-z0-9\-_=]{10,}\b"
)
_PASSWORD_RE: Pattern[str] = re.compile(r"(?i)\b(password|pwd)[=:]?\s*[A-Za-z0-9\-_=]{6,}\b")

_REPLACEMENT = "[REDACTED]"


def _redact_pattern(text: str, pattern: Pattern[str]) -> str:
    return pattern.sub(_REPLACEMENT, text)


def redact_text(text: str) -> str:
    """Redact common PII from a string.

    The function applies a series of regex substitutions for email addresses,
    phone numbers, IP addresses, API keys/tokens, and passwords.
    """
    if not isinstance(text, str):
        return text
    for pat in (_EMAIL_RE, _PHONE_RE, _IP_RE, _APIKEY_RE, _PASSWORD_RE):
        text = _redact_pattern(text, pat)
    return text
