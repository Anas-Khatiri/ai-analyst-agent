from __future__ import annotations

from datetime import UTC, datetime

from domain.evidence_ledger import EvidenceLedger, fingerprint
from domain.finding import EvidenceItem, Finding, TimeWindow

_WINDOW = TimeWindow(start=datetime.now(UTC), end=datetime.now(UTC))


def _evidence_item(evidence_id: str, subject: str, metric: str, source_skill: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        subject=subject,
        metric=metric,
        value=1.0,
        time_window=_WINDOW,
        source_skill=source_skill,
    )


def _finding(evidence: list[EvidenceItem]) -> Finding:
    return Finding(investigation_summary="synthetic", evidence=evidence, confidence_score=0.9)


def test_fingerprint_normalizes_case_and_whitespace() -> None:
    item_a = _evidence_item("a", " User_Zipcode ", "Null_Rate", "skill_a")
    item_b = _evidence_item("b", "user_zipcode", "null_rate", "skill_b")
    assert fingerprint(item_a) == fingerprint(item_b)


def test_add_finding_appends_all_evidence() -> None:
    ledger = EvidenceLedger(incident_id="INC-1")
    finding = _finding([_evidence_item("e1", "transaction_amount", "psi", "data_drift_analysis")])

    ledger.add_finding("data_drift_analysis", finding, wave_index=0)

    assert len(ledger.entries) == 1
    assert ledger.entries[0].source_skill == "data_drift_analysis"
    assert ledger.entries[0].source_wave == 0


def test_add_finding_links_cross_skill_corroboration() -> None:
    ledger = EvidenceLedger(incident_id="INC-1")
    finding_a = _finding([_evidence_item("e1", "user_zipcode", "null_rate", "skill_a")])
    finding_b = _finding([_evidence_item("e2", "user_zipcode", "null_rate", "skill_b")])

    ledger.add_finding("skill_a", finding_a, wave_index=0)
    ledger.add_finding("skill_b", finding_b, wave_index=0)

    entry_a, entry_b = ledger.entries
    assert entry_b.entry_id in entry_a.corroborates
    assert entry_a.entry_id in entry_b.corroborates


def test_add_finding_does_not_self_corroborate_same_skill() -> None:
    ledger = EvidenceLedger(incident_id="INC-1")
    finding = _finding([_evidence_item("e1", "user_zipcode", "null_rate", "skill_a")])

    ledger.add_finding("skill_a", finding, wave_index=0)
    ledger.add_finding("skill_a", finding, wave_index=1)

    assert all(not entry.corroborates for entry in ledger.entries)


def test_fingerprints_for_skill() -> None:
    ledger = EvidenceLedger(incident_id="INC-1")
    finding = _finding([_evidence_item("e1", "transaction_amount", "psi", "data_drift_analysis")])
    ledger.add_finding("data_drift_analysis", finding, wave_index=0)

    fps = ledger.fingerprints_for_skill("data_drift_analysis")
    assert len(fps) == 1
