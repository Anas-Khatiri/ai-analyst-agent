# Agent Specification: Skill Contract

*   **Status**: Approved
*   **Owner**: ML Platform Architect
*   **Document Type**: Interface Behavioral Specification (implementation-independent)
*   **Companion To**: [`ml_analyst_agent.md`](../agents/ml_analyst_agent.md), [`skill_selection_engine.md`](skill_selection_engine.md), [`evidence_model.md`](evidence_model.md)
*   **Related Documents**: [`SYSTEM_SPEC.md`](SYSTEM_SPEC.md), [`SYSTEM_ARCHITECTURE.md`](../architecture/SYSTEM_ARCHITECTURE.md), [`ADR-001-dynamic-skills.md`](../decisions/ADR-001-dynamic-skills.md), [`ADR-002-mcp.md`](../decisions/ADR-002-mcp.md), [`ADR-003-confidence-scoring.md`](../decisions/ADR-003-confidence-scoring.md), [`DYNAMIC_DISCOVERY_DESIGN.md`](../design/DYNAMIC_DISCOVERY_DESIGN.md)

This document is the single source of truth for **what a Skill is, what it owes the ML Analyst Agent, and what the ML Analyst Agent is entitled to assume about it.** It is the other half of the interface defined in [`ml_analyst_agent.md §10.1`](../agents/ml_analyst_agent.md#10-collaboration-with-skills) — that document specifies how the agent *consumes* skills; this document specifies what a skill must *provide*.

Where `DYNAMIC_DISCOVERY_DESIGN.md` specifies *how* the registry mechanically loads and calls a skill (implementation), this document specifies *what a skill must behave like* regardless of that implementation (contract). If the two ever appear to disagree, this document governs skill authoring; `DYNAMIC_DISCOVERY_DESIGN.md` governs the loader's internals.

---

## 1. Overview

### 1.1 Purpose

A Skill is a self-contained, independently authored unit of ML/SRE diagnostic expertise. It owns exactly one investigative question (§6), computes deterministically over evidence it gathers itself, and returns a structured finding the ML Analyst Agent can aggregate, rank, and cite without understanding any of the skill's internal logic.

### 1.2 Mission

> A skill should be writable by a domain expert (an ML engineer who understands drift statistics, or an SRE who understands crash-loop diagnostics) who has never seen the ML Analyst Agent's code, and it should be usable by the agent without the agent's authors ever having seen the skill's code.

The contract in this document is what makes that mutual ignorance safe.

### 1.3 Goals

*   Define the **mandatory anatomy** of a skill directory (§2) and its metadata (§3).
*   Define the **execution contract** the agent is entitled to rely on (§4).
*   Define the **output contract** — the shape every skill result must take (§5) — so the agent's Evidence Aggregator never needs skill-specific parsing.
*   Define how a skill computes and reports its **own local confidence** (§6).
*   Define the **security and isolation obligations** every skill must meet (§7).
*   Define how a skill **declares its relationships** to other skills without creating code coupling (§8).
*   Define the **degradation contract** — how a skill reports partial or missing evidence rather than failing opaquely (§9).
*   Define **versioning rules** that let skills evolve without breaking the agent or other skills (§10).

### 1.4 Non-Goals

*   This document does not specify any particular skill's domain heuristics (e.g., PSI thresholds, OOM detection logic) — that lives entirely inside each skill's own `SKILL.md`.
*   A skill does not decide how it is combined with other skills' findings, how hypotheses are ranked, or what the overall investigation confidence is — that is the agent's and `root_cause_prioritization`'s responsibility (see [`ml_analyst_agent.md §10.3`](../agents/ml_analyst_agent.md#10-collaboration-with-skills)), never the individual skill's.
*   A skill does not execute remediation actions; it only *recommends* them.
*   This document does not specify the registry's loading mechanics (module resolution, sandboxing implementation) — see `DYNAMIC_DISCOVERY_DESIGN.md` for that.

---

## 2. Skill Anatomy

Every skill is a single directory under `skills/`, named for the skill itself, containing exactly two kinds of artifact:

```
skills/<skill_name>/
├── SKILL.md              # Specification: metadata, heuristics, contract compliance
└── scripts/
    ├── run_<skill_name>.py       # Public entrypoint — the report script
    └── _<skill_name>_core.py     # Shared deterministic core (required once >1 report exists)
```

*   **`SKILL.md`** is both human documentation and the machine-readable metadata source (§3). It is the *only* file the Dynamic Skill Registry parses to build its index — the registry never inspects script internals to learn what a skill does.
*   **`scripts/`** contains the executable logic. A skill directory with no `SKILL.md` is not a skill and is silently ignored by the registry.
*   A skill directory must **never** import from another skill's `scripts/` directory. Cross-skill relationships are declared data (§8), never cross-skill code imports — this is what keeps skills independently deployable (per [`ml_analyst_agent.md §13`](../agents/ml_analyst_agent.md#13-design-principles), Modularity).

---

## 3. Metadata Contract

Every `SKILL.md` must declare the following metadata, either as YAML frontmatter (per `DYNAMIC_DISCOVERY_DESIGN.md §3.1`) or in an equivalent structured section the registry parser recognizes:

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | Yes | Unique skill identifier; must match the directory name. |
| `description` | `str` | Yes | One-sentence summary used by the agent when reasoning about *which* skill to select — must be specific enough to distinguish this skill from adjacent ones (e.g., not "checks data" but "measures input feature distribution shift via KS/PSI"). |
| `required_inputs` | `dict[str, str]` | Yes | Named parameters and their types that the skill's entrypoint requires. This is the source of truth the agent uses to construct the call — the agent must never guess parameters. |
| `alert_triggers` | `list[str]` | Yes | Alert types for which this skill is a signal-based routing candidate (§8, [`ml_analyst_agent.md §7.1`](../agents/ml_analyst_agent.md#7-skill-selection-strategy)). |
| `script_path` | `str` | Yes | Relative path to the executable entrypoint. |
| `version` | `str` | Yes | Semantic version of this skill's contract surface (§10). |
| `scope_boundary` | `str` | Yes | A one-paragraph statement of what this skill does **not** do, to prevent overlapping responsibility with adjacent skills (mirrors each existing `SKILL.md`'s "What This Skill MUST NOT Do" section). |

Beyond the machine-readable metadata, every `SKILL.md` must retain the narrative sections already established across the 18 existing skills — Overview, Responsibilities, Triggers, Required Inputs, Expected Evidence, Investigation Workflow, Root Cause Heuristics, Outputs, Confidence Scoring, Recommended Actions, Limitations, Collaboration, Example Investigation, Future Improvements — since these are what a human maintainer and the agent's designers use to audit the skill's reasoning. The metadata table above is a strict subset of that document, not a replacement for it.

---

## 4. Execution Contract

### 4.1 Entrypoint Signature

Every skill exposes exactly one public entrypoint, an asynchronous function, consistent with the platform's async-first design ([`SYSTEM_SPEC.md §6`](SYSTEM_SPEC.md)):

*   It accepts only the parameters declared in `required_inputs` — nothing implicit, nothing pulled from ambient global state.
*   It accepts and validates its parameters against a Pydantic model with `extra = "forbid"`, per [`.agents/CONTEXT.md §2.1`](../../.agents/CONTEXT.md); a request with unknown or malformed parameters is rejected before any computation begins.
*   It returns a single structured result conforming to the Finding Contract (§5) — never a raw string, a bare dict, or partially-structured text for the agent to parse itself.

### 4.2 Statelessness

A skill invocation must be a pure function of its declared inputs. It may read whatever external telemetry its inputs point it to (a dataset path, a log query window), but it must not depend on or mutate any state left behind by a previous invocation of itself or of any other skill. Session-level state (the evidence ledger, cross-skill context) is owned exclusively by the agent's Evidence Aggregator ([`ml_analyst_agent.md §3`](../agents/ml_analyst_agent.md#3-architecture)), never by the skill.

### 4.3 Determinism of the Core

The skill's statistical/diagnostic computation must be deterministic: identical inputs produce identical evidence, hypotheses, and confidence score on every run. Determinism is what allows the Root Cause Ranker and Confidence Estimator to treat skill output as reliable evidence rather than a fresh die roll each time (see [`ml_analyst_agent.md §13`](../agents/ml_analyst_agent.md#13-design-principles), Deterministic Orchestration). If a skill's investigation workflow includes an LLM-assisted step (e.g., summarizing a log excerpt), that step must be confined to the `investigation_summary` narrative field — it must never influence `evidence`, `possible_root_causes`, or `confidence_score`, all of which must trace back to deterministic computation.

### 4.4 Timeout Behavior

A skill must complete, fail, or be safely cancellable within the timeout budget assigned to it by the Skill Executor ([`ml_analyst_agent.md §11`](../agents/ml_analyst_agent.md#11-error-handling)). A skill that cannot bound its own runtime (e.g., an unbounded external query) must implement its own internal timeout and return a degraded result with a `limitations` entry rather than relying on the executor's hard cancellation as its only safeguard.

### 4.5 No Raw Shell Execution

Per [`.agents/CONTEXT.md §2.2`](../../.agents/CONTEXT.md), a skill script must never invoke `subprocess`, `os.system`, or any other raw shell execution primitive. All external interaction (databases, Airflow, git, filesystem) must go through the typed wrapper functions in `shared/tools/*.py`, which in the current phase call `services/mock_env/*.py` adapters (see [`.agents/CONTEXT.md §2.5`](../../.agents/CONTEXT.md)). This is enforced mechanically by a Semgrep pre-commit rule, not left to convention.

---

## 5. Output Contract (The Finding)

Every skill returns a **Finding** — a single structured object with a fixed shape, regardless of domain. This is the contract the agent's Evidence Aggregator, Hypothesis Generator, and Root Cause Ranker are built against (see [`ml_analyst_agent.md §10.1`](../agents/ml_analyst_agent.md#10-collaboration-with-skills)); a skill that deviates from this shape cannot be safely aggregated.

| Field | Type | Description |
|---|---|---|
| `investigation_summary` | `str` | Human-readable synopsis of what this skill found. Narrative only — never a source of evidence or ranking input. |
| `evidence` | `list[EvidenceItem]` | Structured, individually-citable data points (§5.1). This is the skill's factual contribution to the shared ledger. |
| `possible_root_causes` | `list[HypothesisCandidate]` | This skill's locally-scoped candidate explanations, each tied to specific `evidence` entries (§5.2). |
| `confidence_score` | `float [0.0, 1.0]` | This skill's own local confidence, computed under its own deterministic matrix (§6) — not the overall investigation confidence. |
| `recommended_actions` | `list[ActionItem]` | Local suggestions in scope for this skill's findings, each tagged with a risk tier. |
| `preventive_actions` | `list[str]` | Longer-horizon suggestions to prevent recurrence of the failure mode this skill investigates. |
| `limitations` | `list[str]` | Anything this skill could not verify: insufficient sample size, missing telemetry, ambiguous signal. Never omitted when applicable — an empty `limitations` list is an explicit claim of full confidence in data completeness. |

### 5.1 `EvidenceItem` Shape

> This is the shape a single skill emits. The deterministic fingerprinting algorithm, deduplication rules, and cross-skill corroboration/conflict detection that operate on this shape once it enters the shared Evidence Ledger are specified authoritatively in [`evidence_model.md`](evidence_model.md).

Every evidence entry must carry enough structure for the agent to fingerprint and deduplicate it (per [`ml_analyst_agent.md §10.2`](../agents/ml_analyst_agent.md#10-collaboration-with-skills)) without understanding the skill's domain:

| Field | Description |
|---|---|
| `subject` | The concrete thing being measured (a feature name, a metric name, a log source, a task id). |
| `metric` | The statistic computed (a KS p-value, a PSI score, an error rate, a restart count). |
| `value` | The observed value. |
| `baseline` | The reference/expected value, where applicable. |
| `time_window` | The window this observation covers. |
| `source_skill` | The emitting skill's `name`, filled automatically by the executor, not the skill itself. |

A skill must never emit evidence whose `subject` + `metric` + `time_window` is ambiguous enough to prevent correct fingerprinting — vague evidence weakens the agent's ability to recognize cross-skill corroboration (§8).

### 5.2 `HypothesisCandidate` Shape

| Field | Description |
|---|---|
| `cause` | A specific, falsifiable causal statement — not a vague category. ("Upstream pipeline null-injection on `user_zipcode`", not "data quality issue.") |
| `supporting_evidence` | References to specific `evidence` entries from this Finding that support the cause. |
| `conflicting_evidence` | References to specific `evidence` entries, if any, that argue against the cause — a skill must surface evidence against its own leading hypothesis, not just for it. |
| `local_confidence` | This skill's own confidence in this specific hypothesis, independent of `confidence_score` (which is the skill's confidence in its overall investigation). |

### 5.3 What a Skill Must Never Do With Its Output

*   Never rank hypotheses *across* skills — a skill only ranks (or scores) hypotheses within its own Finding.
*   Never call another skill to obtain corroborating evidence directly — cross-skill evidence flows only through the agent's Evidence Aggregator.
*   Never combine its own Finding with a prior skill's Finding by reading agent session state — statelessness (§4.2) forbids this even where technically possible.

---

## 6. Confidence Scoring Contract

Each skill must define, in its own `SKILL.md`, a **deterministic confidence matrix** analogous to the one already established in `data_drift_analysis` (High ≥ 0.8 / Medium 0.5–0.79 / Low < 0.5, each band defined by concrete, checkable criteria such as sample size and statistical agreement). This matrix is:

*   **Explainable**: every band's criteria must be stated as concrete, checkable conditions (sample thresholds, statistical test agreement, absence of confounders) — never "the model felt confident."
*   **Local**: it scores only this skill's own findings, never the overall investigation. The agent's Confidence Estimator (see [`ml_analyst_agent.md §9`](../agents/ml_analyst_agent.md#9-confidence-estimation)) is the only component entitled to compute an investigation-wide score, and it does so by aggregating local scores, not by asking any skill to self-assess the whole investigation.
*   **Conservative under uncertainty**: a skill missing data it needs (small sample, unavailable baseline) must lower its own `confidence_score` and add a `limitations` entry — it must never report high confidence while silently working around a data gap.

---

## 7. Security & Isolation Contract

*   **Input validation**: every skill's entrypoint parameters are validated by a Pydantic model with `extra = "forbid"` before any computation runs (§4.1); malformed input is rejected, never coerced or ignored.
*   **PII isolation**: any raw log, metadata, or record content a skill reads must be passed through the platform's deterministic PII-masking utility before it is embedded in `investigation_summary`, `evidence`, or any other field the agent may later place in an LLM context. A skill must never mask PII with its own ad hoc logic — it must use the shared masking utility so masking behavior is uniform and auditable across all 18+ skills.
*   **No secret leakage**: API keys, tokens, and credentials used by a skill to reach its data sources must never appear in `investigation_summary`, `evidence`, logs, or exceptions.
*   **Prompt-injection awareness**: because a skill's `evidence` may originate from untrusted log/metadata content, a skill must not pass that content directly into any LLM-assisted step (§4.3) without the platform's injection-detection pass; suspected injection content is flagged in `limitations`, and the agent's force-escalation rule ([`ml_analyst_agent.md §9.4`](../agents/ml_analyst_agent.md#9-confidence-estimation)) handles the response.
*   **No raw shell execution**: restated from §4.5 because it is enforced as a security boundary, not just a style rule — this is what prevents a compromised or buggy skill script from becoming a remote-code-execution surface.

---

## 8. Collaboration Contract

Skills do not call each other and do not share code, but they **do** declare relationships to one another, entirely as documentation the agent's Skill Selector reads generically:

*   **`alert_triggers`** (§3) drives first-wave, signal-based selection (see [`ml_analyst_agent.md §7.1`](../agents/ml_analyst_agent.md#7-skill-selection-strategy)).
*   A `SKILL.md`'s **"Collaboration With Other Skills"** section must state, in the same three categories used by every existing skill:
    *   *Invoked Before*: skills whose alert this skill's findings typically precede.
    *   *Invoked After / In Parallel*: skills whose output this skill's findings should be correlated with, and under what evidence condition (e.g., "invoked after this skill if performance regresses but no drift is found" — this is exactly the evidence-based routing condition the agent reads, per [`ml_analyst_agent.md §7.2`](../agents/ml_analyst_agent.md#7-skill-selection-strategy)).
    *   *Downstream Consumers*: skills that treat this skill's `possible_root_causes` as input candidates for ranking (typically `root_cause_prioritization`) or summarization (`incident_summary`).
*   These declarations are advisory metadata for the agent's routing logic, not a call graph — a skill must never assume it will actually be invoked in the stated order, and must produce a valid, self-contained Finding regardless of what ran before or after it.

---

## 9. Degradation Contract (Error Handling)

A skill must never let an internal failure surface as an unhandled exception that the agent has to interpret ad hoc. Instead:

| Situation | Required Skill Behavior |
|---|---|
| A required data source is unreachable | Return a Finding with empty/partial `evidence`, `confidence_score` capped low, and a specific `limitations` entry naming the unreachable source — never raise. |
| Sample size is below the skill's own minimum threshold | Return a Finding that says so explicitly in `limitations`, with `confidence_score` reflecting Low band (§6) — never silently proceed as if the sample were sufficient. |
| An unexpected internal error occurs (bug, unhandled type) | Allowed to propagate as an exception; this is the *only* case the Skill Executor treats as "skill unavailable" (per [`ml_analyst_agent.md §11`](../agents/ml_analyst_agent.md#11-error-handling)) rather than a valid degraded Finding. Skills should minimize how often this path is hit — most degradations should be modeled as the two cases above, not as exceptions. |
| The skill's own timeout budget (§4.4) is at risk | Return the best Finding computable so far with `limitations` noting the truncation, rather than exceeding budget and forcing a hard executor cancellation. |

The distinction matters: a **degraded Finding** is still evidence the agent can use (with appropriately lowered confidence); an **unavailable skill** contributes nothing and forces the agent to fall back to whatever other skills it selected (§7.5 in the companion document). Skills should be written to prefer the former whenever a partial, honest answer is possible.

---

## 10. Versioning & Compatibility

*   Each skill declares a `version` (§3) for its contract surface (its `required_inputs` shape and its `Finding` shape).
*   **Additive changes** (new optional input, new evidence field) are backward compatible and do not require a major version bump.
*   **Breaking changes** (removing/renaming a required input, changing an existing field's type or semantics) require a major version bump and must not silently change behavior for the agent — the registry treats a major-version change as effectively a new skill for compatibility purposes.
*   A skill must never change the *meaning* of an existing `alert_triggers` entry (e.g., repurposing `OOM_ERROR` to mean something narrower) without a major version bump — the agent's routing logic and any human runbooks that reference the trigger depend on trigger semantics remaining stable.
*   Deprecating a skill is done by removing its directory; the registry's next scan simply stops offering it, and the agent's fallback behavior (§7.5 of the companion document) covers any incident types that skill used to serve, until a replacement skill is published.

---

## 11. The Shared-Core-Plus-Focused-Reports Pattern

Per [`.agents/CONTEXT.md §6.1`](../../.agents/CONTEXT.md), the moment a skill needs to produce more than one related report, the shared computation must be factored into a private core module *before* the second report script is written:

*   `scripts/_<skill_name>_core.py` owns only Pydantic result models and pure computation functions — no CLI, no `argparse`, no demo/fixture data, and no dependency on any specific caller's config shape.
*   Core functions take plain scalar/primitive parameters (`bool`, `float`, `str`, lists of primitives) — never a config object owned by one specific report script.
*   `scripts/run_<skill_name>.py` (and any additional report scripts) import only from the shared core, never from each other.
*   This pattern exists so that a skill's second report is a genuine reuse of tested logic, not a copy-paste fork that silently diverges from the first report's heuristics over time.

---

## 12. Testing & Evaluation Contract

*   All deterministic core logic (statistical computations, threshold evaluation, confidence-matrix evaluation) must be unit-tested with `pytest` against fixed evidence fixtures, asserting on types, thresholds, and exact numeric outputs — per [`.agents/CONTEXT.md §4`](../../.agents/CONTEXT.md).
*   A skill must never be tested by asserting on the literal text of `investigation_summary` or any other narrative field — those are not contract-bearing and may legitimately vary in wording between runs if an LLM-assisted step is involved (§4.3).
*   If a skill includes any LLM-assisted narrative step, its *qualitative* behavior (is the summary accurate, readable, non-misleading) is evaluated through the platform's LLM-as-judge EDD harness, scored 1–5, never through pytest string matching.
*   Because a skill's entrypoint is a pure, stateless function (§4.2, §4.3), it must be fully testable in isolation, with no need to spin up the ML Analyst Agent, the registry, or any other skill.

---

## 13. Extensibility — Adding a New Skill

Publishing a new skill requires no change to the ML Analyst Agent, the registry, or any existing skill. The checklist for a compliant new skill:

1.  Create `skills/<new_skill_name>/SKILL.md` with the full narrative sections (§3) plus the required metadata table.
2.  Declare accurate, non-overlapping `alert_triggers` and a precise `scope_boundary` that does not duplicate an existing skill's responsibility (see [`ml_analyst_agent.md §7.1`](../agents/ml_analyst_agent.md#7-skill-selection-strategy) and [`.agents/CONTEXT.md §6.2`](../../.agents/CONTEXT.md), One Tool, One Question).
3.  Implement `scripts/run_<new_skill_name>.py` (and `_<new_skill_name>_core.py` once a second report is needed, §11) conforming to the Execution Contract (§4) and Output Contract (§5).
4.  Define a local, explainable confidence matrix (§6).
5.  Route all external data access through `shared/tools/*.py` wrappers — never raw shell execution (§4.5, §7).
6.  Write pytest unit tests against the core computation with fixed fixtures (§12).
7.  Document this skill's relationship to adjacent skills in its "Collaboration With Other Skills" section (§8).
8.  Land the directory. The next registry scan makes it available; no agent code, prompt, or configuration changes are required or permitted.

---

## 14. Anti-Patterns — What a Skill Must Never Do

*   **Bundle unrelated questions** into one Finding (e.g., computing drift *and* performance regression *and* a retraining recommendation in a single skill) — split by question, per [`.agents/CONTEXT.md §6.2`](../../.agents/CONTEXT.md).
*   **Call another skill's script directly** — relationships are declared metadata (§8), never code imports.
*   **Perform cross-skill ranking or combination** — that is exclusively `root_cause_prioritization`'s and the agent's job (§5.3, §6).
*   **Shell out** to any CLI or external process (§4.5, §7).
*   **Silently swallow a data gap** and report high confidence anyway (§6, §9).
*   **Log or embed secrets/PII** in any field that may reach the LLM context or persisted logs (§7).
*   **Depend on session state** left by a previous invocation of itself or another skill (§4.2).
*   **Assert on LLM-generated text** in its own test suite (§12).

---

## 15. Future Improvements

*   **Skill Certification Linter**: A static-analysis tool (Semgrep-based, alongside the existing shell-execution check) that mechanically verifies a new skill's compliance with this contract — Pydantic `extra="forbid"` usage, no cross-skill imports, presence of a confidence matrix — before it can be merged.
*   **Containerized Skill Sandboxing**: As noted in `SYSTEM_ARCHITECTURE.md §5`, running skill scripts inside ephemeral containers would let this contract's isolation guarantees (§7) be enforced by the runtime itself rather than by code review alone.
*   **Formal Schema Registry**: Publishing the `Finding`/`EvidenceItem`/`HypothesisCandidate` shapes (§5) as versioned JSON Schema artifacts, so cross-team skill authors can validate conformance without reading this document by hand.
*   **Skill Marketplace / Catalog UI**: A browsable index of all registered skills, their `alert_triggers`, `scope_boundary`, and declared collaboration relationships, generated automatically from `SKILL.md` metadata (§3) — giving humans the same registry view the agent has.
*   **Cross-Skill Evidence Schema Validation**: Automated checks that two skills claiming to corroborate the same signal (§8) actually use compatible `EvidenceItem.subject`/`metric` naming, so fingerprinting (§5.1) doesn't silently fail to recognize real corroboration due to naming drift between independently authored skills.
