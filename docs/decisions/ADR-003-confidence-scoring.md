# ADR-003: Deterministic Confidence Scoring

*   **Status**: Approved
*   **Owner**: ML Platform Architect
*   **Decided on**: 2026-07-04
*   **Related Documents**: [`../agents/ml_analyst_agent.md §9`](../agents/ml_analyst_agent.md#9-confidence-estimation), [`../specifications/skill_contract.md §6`](../specifications/skill_contract.md), [`../specifications/root_cause_analysis.md`](../specifications/root_cause_analysis.md)

---

## 1. Context & Motivation (Why)

### Problem Statement

Every Incident Report Pipeline Sentinel produces carries a confidence score that determines whether recommended actions may auto-execute, require human approval, or must be escalated outright (see [`ml_analyst_agent.md §9.4`](../agents/ml_analyst_agent.md#9-confidence-estimation)). Getting this score wrong in either direction is costly: too-high confidence on a wrong diagnosis risks an incorrect auto-executed action in production; too-low confidence on a correct diagnosis buries SREs in unnecessary manual review. This ADR records how that score is computed and why.

### Motivation

The obvious, cheapest implementation — ask the LLM "on a scale of 0 to 1, how confident are you?" — is a well-documented failure mode in agentic systems: LLM self-reported confidence is poorly calibrated, sensitive to prompt phrasing, not reproducible across runs, and does not reliably track actual evidence strength. A platform whose entire value proposition is trustworthy, auditable root cause diagnosis cannot rest its most safety-critical number on that mechanism.

---

## 2. Options Evaluated (What)

### Option A: LLM Self-Reported Confidence (Rejected)

Prompt the model, after reasoning over the evidence, to state a numeric confidence for its own conclusion.

*   *Pros*: Trivial to implement; no extra computation.
*   *Cons*: Not reproducible (the same evidence can yield different self-reported scores across runs); not explainable (no way to audit *why* the model chose 0.75 over 0.6); empirically prone to overconfidence, and directly contradicts the platform-wide rule that cross-tool combination must be deterministic computation, never LLM judgment ([`.agents/CONTEXT.md §6.3`](../../.agents/CONTEXT.md)).

### Option B: Learned Confidence Model (Rejected For Now)

Train a statistical or ML model on historical incidents (evidence pattern → human-confirmed correctness) to predict confidence.

*   *Pros*: Could, in principle, be better calibrated than a hand-authored heuristic, and could improve over time.
*   *Cons*: Requires a training set of historical incidents with confirmed ground-truth outcomes, which does not exist yet — Pipeline Sentinel has not run a single production investigation as of this decision. Building this now would mean training on nothing, i.e., not actually building it. Revisit once sufficient human-confirmed incident history accumulates (see §5 and [`ml_analyst_agent.md §15`](../agents/ml_analyst_agent.md#15-future-improvements), "Learning From Previous Incidents").

### Option C: Deterministic Rule-Based Aggregation (Chosen)

Compute the overall confidence as a fixed, reproducible function of three concrete, auditable inputs: per-skill local confidence, cross-skill evidence agreement, and telemetry completeness — fully specified in [`ml_analyst_agent.md §9`](../agents/ml_analyst_agent.md#9-confidence-estimation).

*   *Pros*: Reproducible (same evidence always yields the same score); explainable (every band is defined by checkable criteria, not vibes); testable without invoking any model, against fixed evidence fixtures; consistent with the platform's deterministic-combination principle.
*   *Cons*: Requires every skill author to hand-author a locally calibrated confidence matrix ([`skill_contract.md §6`](../specifications/skill_contract.md)) — a poorly calibrated local matrix silently propagates into the aggregate. Mitigated by the Skill Certification Linter proposed in [`skill_contract.md §15`](../specifications/skill_contract.md).

---

## 3. Detailed Decision Specification (How)

### 3.1 The Three Input Signals

1.  **Per-skill local confidence**: each skill computes its own confidence under its own explainable, deterministic matrix (sample size, statistical agreement, absence of confounders — see the worked example in `data_drift_analysis`'s `SKILL.md §9`). This is a per-skill obligation, not the agent's.
2.  **Cross-skill agreement**: independent corroboration across skills (two skills' evidence supporting the same hypothesis) raises aggregate confidence above any single skill's own score; unresolved disagreement between competing top hypotheses caps it, regardless of either hypothesis's individual evidence strength.
3.  **Telemetry completeness**: any skill that could not run to completion, returned a degraded result, or recorded a `limitations` entry mechanically lowers the confidence ceiling — a gap is never treated as silent confirmation.

The full computation, banding (High ≥ 0.8 / Medium 0.5–0.79 / Low < 0.5), and forced-escalation overrides are specified authoritatively in [`ml_analyst_agent.md §9`](../agents/ml_analyst_agent.md#9-confidence-estimation) — this ADR records *why* that design was chosen, and defers to that document for the mechanism's full detail.

### 3.2 Division of Ownership

*   Each **skill** owns its own local confidence matrix (§3.1.1) — this cannot be delegated to the agent, since only the skill understands what "sufficient sample size" or "statistical agreement" means in its domain.
*   The **ML Analyst Agent**'s Confidence Estimator owns aggregation only (§3.1.2, §3.1.3) — it never re-derives or second-guesses a skill's local score, it combines already-computed scores.
*   Neither party ever asks an LLM to rate confidence at any stage of this computation.

---

## 4. Consequences & Trade-offs

### Pros

*   A given evidence ledger always produces the same confidence score, on any run, by any implementation that correctly follows the specification — this is a hard requirement for auditability and for unit-testing the Confidence Estimator without a model in the loop.
*   Corroboration and gaps are first-class, visible inputs to the score rather than implicit vibes buried in an LLM's self-assessment.
*   Directly supports the safety posture in [`ml_analyst_agent.md §9.4`](../agents/ml_analyst_agent.md#9-confidence-estimation): auto-execution is only ever gated by a number that can be independently recomputed and defended.

### Cons

*   The aggregate score is only as good as the weakest skill's local matrix — a skill author who defines an overly generous confidence band silently inflates every investigation that relies on that skill. This is an accepted cost during Phase 3–5, mitigated procedurally by code review and, eventually, mechanically (§5).
*   Compared to a learned model, this approach cannot yet exploit historical correctness patterns (e.g., "this skill's High-confidence findings are, empirically, only right 70% of the time") — accepted deliberately, per Option B's rejection, until sufficient history exists.

---

## 5. Future Improvements

*   **Empirical Recalibration**: once enough human-confirmed incident outcomes accumulate, compare each skill's local confidence claims against confirmed correctness and adjust that skill's matrix — or the aggregate weighting — accordingly (see [`ml_analyst_agent.md §15`](../agents/ml_analyst_agent.md#15-future-improvements)).
*   **Skill Certification Linter**: mechanically verify, at merge time, that a new or modified skill's confidence matrix meets minimum rigor requirements (concrete thresholds, no vague bands) — extending the linter proposed in [`skill_contract.md §15`](../specifications/skill_contract.md).
*   **Confidence Drift Monitoring**: track each skill's confidence-band distribution over time in production to detect a skill whose local calibration has silently drifted (e.g., due to an upstream data change invalidating its thresholds).
