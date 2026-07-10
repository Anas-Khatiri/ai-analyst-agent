from infra.security.redaction import redact_text


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
