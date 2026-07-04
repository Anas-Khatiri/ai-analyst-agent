# Specification: Root Cause Analysis

*   **Status**: Approved
*   **Owner**: ML Platform Architect
*   **Document Type**: Component Behavioral Specification (implementation-independent)
*   **Companion To**: [`../agents/ml_analyst_agent.md §8`](../agents/ml_analyst_agent.md#8-reasoning-strategy), [`evidence_model.md`](evidence_model.md)
*   **Related Documents**: [`skill_selection_engine.md`](skill_selection_engine.md), [`incident_schema.md`](incident_schema.md), [`ADR-003-confidence-scoring.md`](../decisions/ADR-003-confidence-scoring.md)

This document is the single source of truth for how a populated Evidence Ledger (per [`evidence_model.md`](evidence_model.md)) becomes a ranked, explainable set of root causes. It formalizes the Hypothesis Generator and Root Cause Ranker stages of the ML Analyst Agent's architecture (see [`ml_analyst_agent.md §3`](../agents/ml_analyst_agent.md#3-architecture)) and the deterministic-combination role played by the `root_cause_prioritization` skill.

---

## 1. Overview

### 1.1 Purpose

Evidence alone is not a diagnosis. Given a ledger full of independently-produced `EvidenceItem`s and per-skill `HypothesisCandidate`s (per [`skill_contract.md §5.2`](skill_contract.md)), something must decide: which causal explanations are actually credible, how they compare against each other, and in what order — with a fully auditable trail back to the evidence that justifies each ranking. That is Root Cause Analysis (RCA) as specified here.

### 1.2 Scope Boundary

This document governs:
*   How candidate hypotheses are synthesized from the Evidence Ledger (§2).
*   How those hypotheses are scored and ordered (§3).
*   How competing and conflicting hypotheses are handled (§4, §5).
*   The explainability obligations on the ranked output (§6).

This document does **not** govern: which skills produced the evidence in the first place (that is [`skill_selection_engine.md`](skill_selection_engine.md)); the shape of the evidence itself (that is [`evidence_model.md`](evidence_model.md)); or how the ranked output feeds into the overall investigation confidence number (that is [`ADR-003-confidence-scoring.md`](../decisions/ADR-003-confidence-scoring.md), which consumes this document's output as one of its inputs — margin between top hypotheses, §7).

### 1.3 Deterministic Combination, Not LLM Judgment

Per [`.agents/CONTEXT.md §6.3`](../../.agents/CONTEXT.md), combining multiple skills' findings into a ranked conclusion is a deterministic computation, exposed as its own tool (`root_cause_prioritization`), never something the agent derives by reasoning in prose over raw evidence. Every rule in this document describes that deterministic computation's behavior — it is a specification of a pure function's contract, not a description of free-form model reasoning.

---

## 2. Hypothesis Generation

### 2.1 Source of Hypotheses

A candidate hypothesis originates from exactly one place: a `HypothesisCandidate` entry inside some skill's `Finding.possible_root_causes` (per [`skill_contract.md §5.2`](skill_contract.md)). The Hypothesis Generator never invents a cause that no skill proposed — it only collects, deduplicates, and structures what skills have already proposed.

### 2.2 Hypothesis Object

| Field | Type | Description |
|---|---|---|
| `hypothesis_id` | `str` | Stable identifier for this hypothesis within the investigation. |
| `cause` | `str` | The specific, falsifiable causal statement, carried over from the originating `HypothesisCandidate.cause`. |
| `contributing_skills` | `list[str]` | Every skill that proposed this hypothesis (§2.3) or whose evidence was folded in as supporting/conflicting. |
| `supporting_evidence` | `list[str]` | Evidence Ledger fingerprints (per [`evidence_model.md §3`](evidence_model.md)) supporting this hypothesis. |
| `conflicting_evidence` | `list[str]` | Evidence Ledger fingerprints arguing against this hypothesis. |
| `score` | `float` | Assigned by the Ranking Function (§3); absent until ranking runs. |

### 2.3 Cross-Skill Hypothesis Merging

Two skills may independently propose causes that are, in substance, the same explanation (e.g., one skill says "upstream null-injection on `user_zipcode`" and a second, corroborating skill's finding independently points at the same subject). These are merged into a single Hypothesis object with both skills listed in `contributing_skills`, rather than kept as two separate, competing hypotheses — merging is triggered when two `HypothesisCandidate.cause` statements cite overlapping `supporting_evidence` fingerprints (per [`evidence_model.md §5.1`](evidence_model.md), corroboration). Hypotheses that are merely topically similar but do not share a fingerprinted evidence link remain distinct.

### 2.4 No Premature Pruning

Every hypothesis with at least one `supporting_evidence` entry is carried into ranking (§3), even ones a later stage will rank low. A hypothesis is only ever dropped from the *published* report for being below a documented noise floor (§4.3) — it is never silently discarded during generation on the grounds that it seems unlikely.

---

## 3. The Ranking Function

### 3.1 Purpose

`root_cause_prioritization` takes the full set of Hypothesis objects (§2.2) and the Evidence Ledger and produces a strict order, with a `score` per hypothesis. The function is deterministic: the same hypothesis set and ledger always produce the same order and scores.

### 3.2 Scoring Factors

Each hypothesis's score is a function of the following factors — all derived structurally from the ledger and hypothesis object, never from free-form judgment:

| Factor | Effect on Score | Rationale |
|---|---|---|
| **Evidence specificity** | Higher for evidence tightly scoped to a specific subject/mechanism (e.g., a named feature's null-rate spike) vs. a broad, dataset-wide signal. | A precise mechanism is a stronger causal claim than a diffuse one. |
| **Evidence magnitude** | Higher for evidence further from baseline/threshold (e.g., a PSI of 0.32 vs. 0.11; a null rate of 18% vs. 2%). | Larger deviations are less plausibly noise. |
| **Corroboration count** | Higher for hypotheses whose `supporting_evidence` includes entries independently corroborated by more than one skill (per [`evidence_model.md §5.1`](evidence_model.md)). | Independent agreement across skills is stronger than any single skill's claim. |
| **Conflicting evidence penalty** | Lower for hypotheses with any `conflicting_evidence` entries, proportional to the conflicting evidence's own specificity and magnitude. | A hypothesis actively contradicted by data is weaker, not merely "also possible." |
| **Temporal correlation** | Higher when the hypothesis's supporting evidence's timing coincides with a known event (e.g., a deployment timestamp supplied via Context Metadata, per [`incident_schema.md §3.4`](incident_schema.md)) that plausibly explains the mechanism. No skill in the current catalog surfaces this kind of event directly, so this factor is presently dormant — it activates automatically once a skill contributing such evidence is added, with no change to the ranking function itself. | Coincidence in time with a known change is corroborating context, not proof by itself. |

### 3.3 What the Ranking Function Must Never Use

The ranking function never takes as input: a skill's `investigation_summary` narrative text, any LLM-generated commentary, or any factor not traceable to a structural property of the ledger or hypothesis object (§3.2). If a factor cannot be computed deterministically from the ledger, it is not a legitimate scoring input.

### 3.4 Output

The Ranking Function returns an ordered `list[RankedCause]` — the same object referenced in [`incident_schema.md §4.2`](incident_schema.md) — where each entry carries its `score`, `supporting_evidence`, `conflicting_evidence`, and a rationale string mechanically assembled from which factors (§3.2) drove the score (never a freely-generated explanation).

---

## 4. Handling Competing Hypotheses

### 4.1 Multiple Surviving Hypotheses Are Normal

An investigation frequently produces more than one credible hypothesis — a primary cause and one or more contributing factors (see the worked example, §7). The Ranking Function does not collapse this down to a single cause artificially; it publishes the full ordered list, and the Recommendation Generator (per [`ml_analyst_agent.md §3`](../agents/ml_analyst_agent.md#3-architecture)) may act on more than one ranked entry (e.g., an immediate fix for the primary cause, a preventive action addressing a contributing one).

### 4.2 Tie-Breaking

When two hypotheses' scores fall within a configured negligible margin of each other, both are published as co-ranked — the Ranking Function does not arbitrarily break a genuine tie to produce an artificially decisive answer. Whether that near-tie *reduces confidence* depends on why the two hypotheses are still separate: hypothesis merging (§2.3) already combines anything sharing a resolved evidence fingerprint, so two hypotheses that remain distinct are, by construction, about *different* evidence — several such hypotheses scoring similarly is multiple well-supported findings (§4.1), not ambiguity. A near-tie is only surfaced (per [`ADR-003-confidence-scoring.md §3.1`](../decisions/ADR-003-confidence-scoring.md)) as a reason for reduced confidence when the co-ranked hypotheses actually contradict each other — i.e., at least one carries `conflicting_evidence` against the other — since that is the case where the investigation genuinely cannot tell which of two competing explanations is correct.

### 4.3 The Noise Floor

A hypothesis whose score falls below a configured noise floor (e.g., support drawn from a single low-magnitude, uncorroborated, and partially conflicting evidence entry) is omitted from the *published* ranking, but is retained in the investigation's internal audit record (per [`evidence_model.md §2.4`](evidence_model.md), append-only ledger) — omission from the report is not deletion from history.

---

## 5. Rejection Criteria

A hypothesis is down-weighted or excluded from the credible ranking — never silently deleted from the record — when:

*   Its `conflicting_evidence` includes an entry whose specificity and magnitude (§3.2) exceed its `supporting_evidence`'s own.
*   It is redundant with a higher-scoring, merged hypothesis (§2.3) and contributes no independent evidence beyond what the merged hypothesis already carries.
*   It falls below the noise floor (§4.3).

A rejected hypothesis's `conflicting_evidence` linkage is exactly what lets the published report explain, if asked, *why* a plausible-sounding alternative was not the conclusion — this is a required capability, not an optional nicety (§6).

---

## 6. Explainability Requirements

Every entry in the published `root_cause_ranking` (per [`incident_schema.md §4.2`](incident_schema.md)) must satisfy:

*   **Traceability**: every `supporting_evidence` and `conflicting_evidence` reference resolves to an actual Evidence Ledger fingerprint (per [`evidence_model.md §3`](evidence_model.md)) — never a paraphrase or a claim without a resolvable citation.
*   **Mechanical rationale**: the rationale string is assembled from which scoring factors (§3.2) applied and by how much — a human reading it can verify the score, not just trust it.
*   **No unexplained gaps**: if a hypothesis a human might expect to see (e.g., one two skills' findings seem to point at) is absent from the ranking, its rejection reason (§5) must be reconstructable from the retained audit record, even if it isn't included in the published report itself.

---

## 7. Interaction With Confidence Estimation and Recommendations

*   The **margin** between the top-ranked and second-ranked hypothesis's scores is one of the three structural inputs [`ADR-003-confidence-scoring.md §3.1`](../decisions/ADR-003-confidence-scoring.md) uses for cross-skill agreement / disagreement — this document produces that margin; it does not itself compute the confidence score.
*   The **top-ranked hypothesis (or hypotheses, in a co-ranked case)** is what the Recommendation Generator (per [`ml_analyst_agent.md §3`](../agents/ml_analyst_agent.md#3-architecture)) maps to concrete actions — a hypothesis that did not survive ranking never generates a recommended action, even if some skill originally proposed it.

---

## 8. End-to-End Example

Continuing the `Fraud_Detection_XGBoost` investigation (see [`ml_analyst_agent.md §14`](../agents/ml_analyst_agent.md#14-example-investigation) and [`evidence_model.md §9`](evidence_model.md#9-example-ledger-walkthrough)):

### Hypotheses Generated (§2)

*   **H1**: "Upstream pipeline failure causing missing `user_zipcode` values" — `contributing_skills = [data_drift_analysis]`, `supporting_evidence = [user_zipcode::null_rate::current_window]`.
*   **H2**: "Organic transaction-volume increase" — `contributing_skills = [data_drift_analysis]`, `supporting_evidence = [transaction_amount::psi::current_window]`.

Both hypotheses cite the F1-score regression (`f1_score::model_performance::current_window`, from `model_performance_analysis`) as the symptom being explained, but neither conflicts with the other's specific evidence — no `conflicting_evidence` entries exist for either.

### Scoring (§3.2)

*   **H1** scores higher: `user_zipcode`'s null-rate spike is highly specific (a single, named, high-importance feature), high-magnitude (18.5% vs. a 0.02% baseline — roughly a 900x deviation), and — because `user_zipcode` is a documented high-importance feature for regional fraud heuristics — carries a strong mechanistic link to the observed F1 drop.
*   **H2** scores lower: `transaction_amount`'s shift is real (PSI = 0.32, above the severe-drift threshold) but less specific as a sole explanation for a fraud-detection F1 drop, and no corroborating evidence ties it as tightly to the specific failure mechanism as H1's null-rate spike does.

### Ranking Output

`root_cause_ranking = [H1 (score: high, primary), H2 (score: medium, contributing)]` — both are published, per §4.1, since H2 remains a credible contributing factor even though it is not primary.

### Downstream Use

The Recommendation Generator maps H1 to the immediate imputation fix and the upstream logging defect fix (per [`ml_analyst_agent.md §14`](../agents/ml_analyst_agent.md#14-example-investigation)); the margin between H1 and H2's scores (a clear, non-negligible gap) feeds into the overall confidence computation as evidence of low cross-hypothesis disagreement, contributing to the High (0.92) confidence score in the original worked example.

---

## 9. Design Principles

*   **Evidence-First, Always**: no hypothesis exists that a skill did not first propose with cited evidence (§2.1); ranking never introduces a new cause.
*   **Deterministic, Auditable Scoring**: every score is reconstructable from structural evidence properties (§3.2) — never from LLM prose judgment (§1.3).
*   **Honest Multi-Causality**: an investigation with more than one credible cause says so (§4.1) rather than forcing a single, artificially clean answer.
*   **Nothing Silently Vanishes**: rejected and below-noise-floor hypotheses remain in the audit record (§4.3, §5) even when omitted from the published report.
*   **Explainable by Construction**: the rationale for every ranked cause — and for every rejected one — is mechanically derivable, not asserted (§6).

---

## 10. Future Improvements

*   **Weight Calibration From Outcomes**: once sufficient human-confirmed investigation outcomes exist, calibrate the relative weighting of the scoring factors in §3.2 empirically rather than by initial expert judgment (mirrors [`ADR-003-confidence-scoring.md §5`](../decisions/ADR-003-confidence-scoring.md)).
*   **Historical Hypothesis Retrieval**: surface similar past investigations' confirmed root causes as supporting context during ranking (without letting them substitute for this investigation's own evidence), consistent with [`ml_analyst_agent.md §15`](../agents/ml_analyst_agent.md#15-future-improvements).
*   **Multi-Cause Interaction Modeling**: extend the Ranking Function to express not just an ordered list but explicit causal relationships between co-ranked hypotheses (e.g., "H2 amplified the impact of H1" rather than two independent parallel causes), where evidence supports such a relationship.
