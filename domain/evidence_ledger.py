from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from domain.finding import EvidenceItem, Finding


def normalize_token(value: str) -> str:
    return value.strip().lower()


def bucket_time_window(item: EvidenceItem) -> str:
    """Simplified time-bucket per evidence_model.md §3.2: same calendar day.

    A full implementation would bucket by the investigation's evaluation
    window rather than a fixed calendar day; this is deliberately coarse
    until a real windowing need arises (no current skill emits evidence
    spanning multiple days within one investigation).
    """
    return item.time_window.start.date().isoformat()


def fingerprint(item: EvidenceItem) -> str:
    """Deterministic evidence fingerprint per evidence_model.md §3: subject::metric::time_bucket.

    This is the single, shared implementation — skills and combination
    skills (e.g. root_cause_prioritization) must resolve corroboration
    through this function rather than reimplementing their own.
    """
    subject = normalize_token(item.subject)
    metric = normalize_token(item.metric)
    return f"{subject}::{metric}::{bucket_time_window(item)}"


class LedgerEntry(BaseModel):
    """Per evidence_model.md §2.3.

    `entry_id` is an addition beyond the literal spec table: the spec's
    `corroborates`/`conflicts_with` fields are typed as fingerprint lists,
    but a bare fingerprint cannot disambiguate *which* entry among possibly
    several sharing it — so this implementation links entries by `entry_id`
    instead, while still exposing `fingerprint` as its own field.
    """

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    fingerprint: str
    evidence_item: EvidenceItem
    source_skill: str
    source_wave: int
    recorded_at: datetime
    corroborates: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)


class EvidenceLedger(BaseModel):
    """The session-scoped, append-only evidence store per evidence_model.md §2."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    entries: list[LedgerEntry] = Field(default_factory=list)
    wave_index: int = 0

    def add_finding(self, skill_name: str, finding: Finding, wave_index: int) -> None:
        """Appends every EvidenceItem in `finding` as a new LedgerEntry.

        Never mutates or removes existing entries (§2.4, append-only).
        Cross-skill entries sharing a fingerprint are linked via
        `corroborates` (§5.1); an entry from the same skill sharing a
        fingerprint with a prior one (e.g. a retried execution) is still
        appended but not treated as independent corroboration of itself.
        """
        recorded_at = datetime.now(UTC)
        for index, item in enumerate(finding.evidence):
            entry_id = f"{skill_name}#{wave_index}#{index}"
            fp = fingerprint(item)
            new_entry = LedgerEntry(
                entry_id=entry_id,
                fingerprint=fp,
                evidence_item=item,
                source_skill=skill_name,
                source_wave=wave_index,
                recorded_at=recorded_at,
            )
            for existing in self.entries:
                if existing.fingerprint == fp and existing.source_skill != skill_name:
                    existing.corroborates.append(new_entry.entry_id)
                    new_entry.corroborates.append(existing.entry_id)
            self.entries.append(new_entry)
        self.wave_index = max(self.wave_index, wave_index)

    def fingerprints_for_skill(self, skill_name: str) -> set[str]:
        return {entry.fingerprint for entry in self.entries if entry.source_skill == skill_name}
