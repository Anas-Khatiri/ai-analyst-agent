# Specification: Evidence Model

*   **Status**: Approved
*   **Owner**: ML Platform Architect
*   **Document Type**: Data Model Specification (implementation-independent)
*   **Companion To**: [`skill_contract.md §5`](skill_contract.md), [`../agents/ml_analyst_agent.md §10`](../agents/ml_analyst_agent.md#10-collaboration-with-skills)
*   **Related Documents**: [`incident_schema.md`](incident_schema.md), [`root_cause_analysis.md`](root_cause_analysis.md), [`skill_selection_engine.md`](skill_selection_engine.md)

This document is the single source of truth for how evidence is represented, fingerprinted, deduplicated, and tracked **across an entire investigation** — as opposed to [`skill_contract.md §5`](skill_contract.md), which specifies the shape of a *single skill's* output (`Finding`, `EvidenceItem`, `HypothesisCandidate`) in isolation. Where that document governs what one skill hands over, this document governs what happens to every skill's evidence once it enters the shared **Evidence Ledger**.

---

## 1. Overview

### 1.1 Purpose

An investigation may execute several skills across several waves (see [`skill_selection_engine.md §5`](skill_selection_engine.md#5-sequential-vs-parallel-execution)). Each skill returns its own `Finding`, containing its own `EvidenceItem` entries (per [`skill_contract.md §5.1`](skill_contract.md)). None of those skills know about each other, and none of them see each other's output. Something has to be the single place where all of this evidence accumulates, gets recognized as corroborating or conflicting, gets deduplicated, and remains queryable for the rest of the investigation and for post-hoc audit. That something is the **Evidence Ledger**, owned by the ML Analyst Agent's Evidence Aggregator component (see [`ml_analyst_agent.md §3`](../agents/ml_analyst_agent.md#3-architecture)).

### 1.2 Scope Boundary

This document specifies:
*   The Evidence Ledger's structure and lifecycle (§2).
*   The fingerprinting algorithm that lets two independently-produced `EvidenceItem`s be recognized as referring to the same underlying signal (§3).
*   Deduplication rules (§4).
*   Corroboration and conflict detection (§5).
*   Provenance and audit requirements (§6).

This document does **not** specify: the internal shape of a `Finding` or `EvidenceItem` as emitted by one skill (that is [`skill_contract.md §5`](skill_contract.md)); how hypotheses are ranked from ledger contents (that is [`root_cause_analysis.md`](root_cause_analysis.md)); or how confidence is computed from ledger completeness (that is [`ADR-003-confidence-scoring.md`](../decisions/ADR-003-confidence-scoring.md)).

---

## 2. The Evidence Ledger

### 2.1 Definition

The Evidence Ledger is the session-scoped, append-only store of every `EvidenceItem` produced by every skill executed during one investigation, keyed by `incident_id` (per [`incident_schema.md §3`](incident_schema.md)).

### 2.2 Structure

| Field | Type | Description |
|---|---|---|
| `incident_id` | `str` | The investigation this ledger belongs to. |
| `entries` | `list[LedgerEntry]` | Every evidence entry recorded so far, in the order they arrived. |
| `wave_index` | `int` | The current investigation wave, incremented each time the Skill Selection Engine is re-invoked (per [`skill_selection_engine.md §6.1`](skill_selection_engine.md#6-evidence-triggered-additional-skill-invocation)). |

### 2.3 `LedgerEntry`

A `LedgerEntry` wraps a single `EvidenceItem` (as defined in [`skill_contract.md §5.1`](skill_contract.md)) with ledger-level bookkeeping:

| Field | Type | Description |
|---|---|---|
| `fingerprint` | `str` | The deterministic fingerprint computed per §3 — the primary key for deduplication and corroboration matching. |
| `evidence_item` | `EvidenceItem` | The original evidence as emitted by the skill (subject, metric, value, baseline, time_window). |
| `source_skill` | `str` | Which skill produced this entry. |
| `source_wave` | `int` | Which investigation wave produced this entry. |
| `recorded_at` | `datetime` | When the Evidence Aggregator wrote this entry. |
| `corroborates` | `list[str]` | Fingerprints of other entries this one independently corroborates (§5.1). |
| `conflicts_with` | `list[str]` | Fingerprints of other entries this one contradicts (§5.2). |

### 2.4 Append-Only Lifecycle

The ledger is **append-only** for the life of an investigation: no entry is ever mutated or deleted once recorded, including entries later found to conflict with other evidence. Superseding or contradicting evidence is recorded as a *new* entry with a `conflicts_with` link (§5.2) — never as an edit or removal of the original. This is what makes an investigation fully auditable after the fact (see §6) and is what [`root_cause_analysis.md`](root_cause_analysis.md) relies on when explaining why a hypothesis was rejected: the contradicting evidence must still be visible, not erased.

---

## 3. Fingerprinting Algorithm

### 3.1 Purpose

A fingerprint is a deterministic key derived from an `EvidenceItem`'s `subject`, `metric`, and `time_window`, such that two `EvidenceItem`s referring to the same underlying real-world signal — even if produced by two different skills that have never heard of each other — resolve to the same fingerprint.

### 3.2 Derivation Rule

`fingerprint = normalize(subject) + "::" + normalize(metric) + "::" + bucket(time_window)`, where:

*   `normalize(subject)` lower-cases and trims the subject identifier (a feature name, a metric name, a log source, a task id) so that trivial casing or whitespace differences across two skills' emissions do not produce spurious distinct fingerprints.
*   `normalize(metric)` applies the same normalization to the metric name.
*   `bucket(time_window)` maps the evidence's time window to a canonical bucket (e.g., the investigation's current evaluation window, rather than each skill's own arbitrarily-phrased window string), so that two skills measuring "the last hour" using slightly different window representations still fingerprint identically.

### 3.3 Why Subject + Metric + Time Window, and Not More

Fingerprinting deliberately ignores `value` and `baseline` — two skills observing the *same* subject and metric in the *same* window, but reporting slightly different measured values (e.g., due to independent sampling), must still be recognized as evidence about the same signal, not as two unrelated observations. Divergence in the *value* two skills report for the same fingerprint is itself potentially interesting (see §5.2) but does not prevent them from sharing a fingerprint.

### 3.4 Skill Author Responsibility

Per [`skill_contract.md §5.1`](skill_contract.md), a skill must never emit an `EvidenceItem` whose `subject`/`metric` naming is so vague that fingerprinting collapses unrelated signals together or fails to unify genuinely identical ones. Skill authors publishing evidence about a commonly-shared subject (e.g., a specific feature name) should use the same naming convention other skills already use for that subject — see the Future Improvement on cross-skill naming validation (§8).

---

## 4. Deduplication Rules

*   **Exact duplicate** (same fingerprint, same `source_skill`, e.g., from a retried execution): the later entry is recorded but flagged as a duplicate of the earlier one and excluded from independent-corroboration counting (§5.1) — a skill cannot corroborate itself.
*   **Cross-skill match** (same fingerprint, different `source_skill`): both entries are retained as separate `LedgerEntry` records, linked via `corroborates` (§5.1) — this is a signal to be surfaced, never collapsed away, since independent corroboration is itself evidence of correctness (per [`ADR-003-confidence-scoring.md §3.1`](../decisions/ADR-003-confidence-scoring.md)).
*   **Near-duplicate windows** (same subject/metric, overlapping but not identical time windows): resolved by the `bucket()` function (§3.2) mapping both to the same canonical bucket wherever the investigation's evaluation window makes them substantively the same observation; genuinely different windows (e.g., one skill measuring the last hour, another measuring the last 24 hours) remain distinct fingerprints and distinct entries.

---

## 5. Corroboration and Conflict Detection

### 5.1 Corroboration

Two `LedgerEntry` records with the same fingerprint but different `source_skill` are marked as mutually corroborating: each entry's `corroborates` list includes the other's fingerprint-entry reference. Corroboration is a structural fact (same fingerprint, independent source) — it is computed by the Evidence Aggregator mechanically, never inferred by an LLM reading both entries.

### 5.2 Conflict

Two entries are marked as conflicting when they share a fingerprint but their `value`s are inconsistent with a single underlying explanation (e.g., one skill's evidence implies a metric is within normal bounds, another's implies it is anomalous, for the same subject and window) — or when one skill's `HypothesisCandidate.conflicting_evidence` (per [`skill_contract.md §5.2`](skill_contract.md)) explicitly cites another entry. Conflicts are never resolved by deleting either entry; both remain in the ledger, linked via `conflicts_with`, and are handed whole to `root_cause_prioritization` for adjudication (per [`root_cause_analysis.md`](root_cause_analysis.md) and [`ml_analyst_agent.md §10.3`](../agents/ml_analyst_agent.md#10-collaboration-with-skills)).

### 5.3 What the Ledger Does Not Do

The Evidence Ledger records corroboration and conflict as structural facts. It does not decide what those facts *mean* for a hypothesis's ranking or the investigation's overall confidence — those interpretations belong to [`root_cause_analysis.md`](root_cause_analysis.md) and [`ADR-003-confidence-scoring.md`](../decisions/ADR-003-confidence-scoring.md) respectively, which consume the ledger's structure as an input.

---

## 6. Provenance and Audit Trail

Every `LedgerEntry` retains `source_skill`, `source_wave`, and `recorded_at` permanently (§2.3) — never summarized away. This is what allows a completed investigation to be fully replayed: an auditor can reconstruct exactly which skill, in which wave, produced any given piece of evidence, and exactly which other entries it was found to corroborate or conflict with. The ledger, in its entirety, is persisted to the platform's long-term audit store (PostgreSQL, per [`../architecture/SYSTEM_ARCHITECTURE.md §2`](../architecture/SYSTEM_ARCHITECTURE.md)) at investigation completion — it is not discarded once the Incident Report (per [`incident_schema.md §4`](incident_schema.md)) is published.

---

## 7. PII and Redaction Boundary

The Evidence Ledger never stores raw, unmasked log or record content. Every `EvidenceItem` a skill emits has already had any PII-bearing raw content deterministic-masked before it reaches the skill's own `Finding` output (per [`skill_contract.md §7`](skill_contract.md) and [`.agents/CONTEXT.md §2.3`](../../.agents/CONTEXT.md)); the ledger is a pass-through store for already-sanitized structured evidence, and it must never be treated as a place where that sanitization can be retroactively applied. If a skill fails to mask upstream content before emitting evidence, that is a skill contract violation to be caught in review/certification (per [`skill_contract.md §15`](skill_contract.md)), not something the ledger compensates for.

---

## 8. Design Principles

*   **Structural, Not Interpretive**: the ledger records facts (what was measured, by whom, and what else it structurally matches or contradicts) — it never interprets what those facts mean for a diagnosis.
*   **Append-Only Auditability**: nothing is ever deleted or overwritten (§2.4); the full evidentiary history of an investigation, including rejected hypotheses' supporting evidence, remains inspectable indefinitely.
*   **Deterministic Fingerprinting**: identical evidence always produces the identical fingerprint (§3), independent of which skill produced it or in what order — this is what makes corroboration detection reproducible rather than a matter of LLM judgment.
*   **Cross-Skill Neutrality**: the ledger has no skill-specific logic; it operates uniformly over any conformant `EvidenceItem`, regardless of domain, which is what lets new skills participate in corroboration/conflict detection with zero ledger changes (consistent with [`ADR-001-dynamic-skills.md`](../decisions/ADR-001-dynamic-skills.md)).

---

## 9. Example Ledger Walkthrough

Continuing the `Fraud_Detection_XGBoost` investigation from [`ml_analyst_agent.md §14`](../agents/ml_analyst_agent.md#14-example-investigation):

1.  **Wave 0**: `model_performance_analysis` writes a `LedgerEntry` with fingerprint `f1_score::model_performance::current_window` (`source_skill=model_performance_analysis`). `data_drift_analysis` writes two entries: `user_zipcode::null_rate::current_window` and `transaction_amount::psi::current_window` (`source_skill=data_drift_analysis`).
2.  **No corroboration yet**: all three fingerprints are distinct subjects, so no `corroborates` links are created at this stage — each skill measured a different signal.
3.  **Hypothesis linkage** (handled downstream by [`root_cause_analysis.md`](root_cause_analysis.md), not the ledger itself): the hypothesis "upstream pipeline failure causing missing `user_zipcode`" cites the `user_zipcode::null_rate` entry as supporting evidence; the F1-score entry is cited as the symptom being explained.
4.  **Audit trail preserved**: even after the investigation concludes, all three entries remain in the ledger with full provenance, so a human reviewing the published Incident Report's `supporting_evidence` (per [`incident_schema.md §4.2`](incident_schema.md)) can trace the root cause ranking back to these exact, timestamped, skill-attributed observations.

---

## 10. Future Improvements

*   **Cross-Skill Subject Naming Validation**: a mechanical check (extending the Skill Certification Linter proposed in [`skill_contract.md §15`](skill_contract.md)) that flags when two skills use inconsistent naming for what is likely the same real-world subject, so fingerprinting doesn't silently fail to unify genuinely corroborating evidence.
*   **Ledger Query API Formalization**: as the platform matures past Phase 5, formalize the read interface the Skill Selection Engine and Root Cause Ranker use to query the ledger (e.g., "all entries with fingerprint prefix X") as its own versioned contract.
*   **Time-Bucket Configurability**: allow the `bucket()` function (§3.2) to be tuned per incident category, since the "same observation window" threshold that makes sense for a latency incident (minutes) differs from what makes sense for a drift incident (days).
