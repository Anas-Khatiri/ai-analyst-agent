# ADR-004: LLM-Driven ReAct Skill Selection as an Alternative Mode

*   **Status**: Approved
*   **Owner**: ML Platform Architect
*   **Decided on**: 2026-07-04
*   **Related Documents**: [`ADR-001-dynamic-skills.md`](ADR-001-dynamic-skills.md), [`ADR-003-confidence-scoring.md`](ADR-003-confidence-scoring.md), [`../agents/ml_analyst_agent.md §13`](../agents/ml_analyst_agent.md#13-design-principles), [`../specifications/skill_selection_engine.md`](../specifications/skill_selection_engine.md)

---

## 1. Context & Motivation (Why)

### Problem Statement

The platform's skill selection is implemented as deterministic metadata matching: `SkillSelectionEngine` matches an incident's `alert_type` against each skill's declared `alert_triggers` (`agents/skill_selection_engine.py`). `ml_analyst_agent.md §13` names "Deterministic Orchestration" as a core design principle specifically so routing is reproducible, not model judgment.

A request was made for a genuine **ReAct agent** (Reasoning + Acting, Yao et al.): an LLM that reads each skill's `description` in prose, reasons about which to invoke, acts (calls it), observes the result, and loops — rather than exact-string `alert_triggers` matching. Taken as a wholesale replacement of `SkillSelectionEngine`, this directly contradicts the "Deterministic Orchestration" principle. This ADR resolves how to honor both the new request and the existing principle.

### Motivation

`alert_triggers` matching is precise but rigid — it can only route an incident whose alert type a skill author anticipated in advance. An LLM reasoning over prose descriptions can, in principle, generalize to alert types or incident phrasings no one explicitly enumerated. That flexibility is genuinely valuable to have available, but it trades away reproducibility — the same incident could select different skills on different runs. The platform should not have to choose one mechanism forever; it should be able to offer both and compare them.

---

## 2. Options Evaluated (What)

### Option A: Replace `SkillSelectionEngine` Entirely With LLM Reasoning (Rejected)

Remove the deterministic engine; every incident's investigative skill selection goes through an LLM reading skill descriptions.

*   *Pros*: Simplest mental model — one selection mechanism. Generalizes to unanticipated alert types.
*   *Cons*: Directly reverses `ml_analyst_agent.md §13`'s "Deterministic Orchestration" principle for the entire platform, not just an experimental path. Every investigation becomes non-reproducible and non-unit-testable the way `SkillSelectionEngine`'s tests currently are (`tests/agents/test_skill_selection_engine.py` asserts exact wave contents given a signature — that becomes impossible). Also risks silently increasing cost/latency and introducing selection failures (hallucinated tool calls, wrong parameters) with no deterministic fallback.

### Option B: Reject the Request, Keep Selection Purely Deterministic (Rejected)

Decline to add LLM-driven selection at all, on the grounds that it conflicts with an established principle.

*   *Pros*: No new non-determinism anywhere in the platform.
*   *Cons*: Ignores a legitimate, explicitly requested capability. The "Deterministic Orchestration" principle was written to protect *combination* (ranking, confidence, reporting) from becoming LLM-judged black boxes — nothing about it requires that *every possible selection mechanism* be deterministic, only that the platform's default, production path is.

### Option C: Hybrid — LLM Reasoning Replaces Only Investigative Selection; Combination Stays Deterministic Regardless (Chosen)

Add a new, separate entrypoint, `agents/react_agent.py::analyze_incident_react`, alongside the existing `agents/ml_analyst_agent.py::analyze_incident`. The ReAct agent uses an LLM (via `google-adk`) to reason over investigative skills' `description` metadata and choose which to call, observing each `Finding` and looping. Once the LLM stops calling tools, the *exact same* terminal-wave execution and report assembly the deterministic agent uses (`execute_wave`, `record_selection`, `assemble_report`, all in `ml_analyst_agent.py`) runs unchanged — ranking, confidence, and report compilation are never touched by the LLM, satisfying [`.agents/CONTEXT.md §6.3`](../../.agents/CONTEXT.md) ("Deterministic Combination, Never LLM Judgment") regardless of which selection mode picked the underlying evidence.

*   *Pros*: Both mechanisms remain available and directly comparable on the same incident. The already-tested deterministic path is untouched — zero regression risk to it. Combination stays deterministic and auditable no matter which selection path ran. `google-adk` is already a project dependency, and `DYNAMIC_DISCOVERY_DESIGN.md §2`'s "Dynamic Tool Wrapper: An adapter that conforms to the ADK `FunctionTool` API" already anticipated exactly this integration point.
*   *Cons*: Two selection mechanisms to maintain going forward. The LLM path cannot be asserted on the way `SkillSelectionEngine`'s tests are (which specific skill gets called can vary run to run) — tests are scoped to structural properties only, per [`.agents/CONTEXT.md §4`](../../.agents/CONTEXT.md)'s rule against asserting on LLM text/choices.

---

## 3. Detailed Decision Specification (How)

### 3.1 Scope of the LLM's Authority

The LLM in `react_agent.py` chooses **only** which *investigative* skill to call and with what parameters. Terminal skills (`root_cause_prioritization`, `incident_summary`) are never exposed to it as callable tools — their `required_inputs` include `dict[str, Finding]`, which an LLM cannot meaningfully construct, and letting it attempt to would reopen exactly the "deterministic combination" boundary this ADR is designed to keep closed.

### 3.2 Tool Description Is the Selection Signal

Each investigative skill becomes a `google.adk.tools.FunctionTool` wrapping a dynamically-synthesized function whose docstring is set to that skill's `SkillMetadata.description` (parsed from `SKILL.md` frontmatter, the same source `SkillSelectionEngine` reads `alert_triggers` from). This is the literal mechanism for "reading skill descriptions in prose" — no new metadata field or duplicate description is introduced.

### 3.3 What Downstream of Selection Never Changes

Once the ReAct loop concludes (the model stops requesting tool calls, or a safety cap is hit), `react_agent.py` calls `SkillSelectionEngine.select_next_wave(...)` for the terminal wave exactly as `analyze_incident` does, then the same `record_selection`/`execute_wave`/`assemble_report` functions. The two entrypoints diverge only in how Wave 0's investigative skills get chosen.

---

## 4. Consequences & Trade-offs

### Pros

*   The platform's default, tested, reproducible path is unaffected.
*   A genuinely different, more flexible selection mode is available for exploration/comparison without weakening the existing guarantees.
*   Combination logic has exactly one implementation regardless of selection mode, so a future change to ranking/confidence/reporting never needs to be made twice.

### Cons

*   Two selection code paths now exist; a future skill author must understand both `alert_triggers` (deterministic) and `description` (LLM-facing) matter, not just one.
*   The ReAct path's behavior is not deterministic and cannot be pinned down by an exact-output unit test — only structural properties, per §3 above.
*   The ReAct path requires a live `GEMINI_API_KEY` and incurs real inference cost/latency per investigation; the deterministic path does not.

---

## 5. Future Improvements

*   **Selection-Mode Comparison Harness**: run the same incident fixture through both entrypoints and diff which skills each selected, as a standing regression signal for how much the two mechanisms agree in practice.
*   **Confidence-Aware Fallback**: if the ReAct agent's tool-call loop produces no investigative Findings at all, fall back to the deterministic engine's signal-based routing for the same incident rather than escalating immediately.
*   **Cost/Latency Budgets**: extend the tool-call safety cap into a configurable budget (max tokens, max wall-clock time) once this mode sees real usage patterns to tune against.
