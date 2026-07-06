import pytest

from shared.security.exceptions import ValidationError
from shared.security.redaction import redact_text
from shared.security.validation import SecureModel


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------
class SamplePayload(SecureModel):
    name: str
    age: int


def test_validation_success() -> None:
    payload = SamplePayload(name="Alice", age=30)
    assert payload.name == "Alice"
    assert payload.age == 30


def test_validation_extra_fields_raise() -> None:
    with pytest.raises(ValidationError):
        SamplePayload(name="Bob", age=25, extra="not allowed")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Redaction tests
# ---------------------------------------------------------------------------
def test_redact_pii() -> None:
    raw = (
        "Contact me at alice@example.com or +1-555-123-4567. "
        "My server is 192.168.1.10. "
        "API_KEY=abcd1234efgh5678ijkl. "
        "Password=Secret123!"
    )
    redacted = redact_text(raw)
    # All PII should be replaced with [REDACTED]
    assert "alice@example.com" not in redacted
    assert "+1-555-123-4567" not in redacted
    assert "192.168.1.10" not in redacted
    assert "abcd1234efgh5678ijkl" not in redacted
    assert "Secret123!" not in redacted
    # The placeholder should appear the expected number of times (5)
    assert redacted.count("[REDACTED]") == 5
