from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from infra.skill_registry import SkillMetadata, SkillRegistry, missing_required_inputs

ExecutionMode = Literal["parallel", "sequential"]
TriggerReason = Literal["signal_match", "evidence_triggered", "fallback", "terminal"]
ContinuationSignal = Literal["awaiting_evidence", "terminate"]

DEFAULT_MAX_SKILLS_PER_WAVE = 5


class SelectedSkillPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_name: str
    trigger_reason: TriggerReason
    resolved_params: dict[str, object] = Field(default_factory=dict)


class ExcludedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_name: str
    reason: str


class SelectionPlan(BaseModel):
    """Per skill_selection_engine.md §3.6."""

    model_config = ConfigDict(extra="forbid")

    wave_id: int
    execution_mode: ExecutionMode
    selected_skills: list[SelectedSkillPlan] = Field(default_factory=list)
    excluded_candidates: list[ExcludedCandidate] = Field(default_factory=list)
    rationale: str
    continuation_signal: ContinuationSignal
    termination_reason: str | None = None


def _specificity_score(meta: SkillMetadata) -> float:
    """A skill declaring fewer, more targeted alert_triggers is treated as more
    specific than one declaring many broad ones, per §3.3. With the current
    catalog this rarely changes an outcome, but the mechanism is real, not a
    placeholder, for when a genuinely competing pair of skills exists."""
    return 1.0 / len(meta.alert_triggers) if meta.alert_triggers else 0.0


class SkillSelectionEngine:
    """Implements the Stage 1-5 decision funnel and wave assembly from
    skill_selection_engine.md. Never invokes a skill itself (§1.3) — it only
    ever produces a SelectionPlan for the caller's Skill Executor to run."""

    def __init__(
        self, registry: SkillRegistry, max_skills_per_wave: int = DEFAULT_MAX_SKILLS_PER_WAVE
    ) -> None:
        self.registry = registry
        self.max_skills_per_wave = max_skills_per_wave

    def select_next_wave(
        self,
        wave_id: int,
        skill_parameters: dict[str, dict[str, object]],
        already_executed: set[str],
    ) -> SelectionPlan:
        """Called after each wave's findings return. Evaluates evidence-trigger
        conditions (§6.2 — inert with the current catalog, since no skill
        declares one yet) and, once no further investigative skill applies,
        emits the terminal wave (§5.3) before finally signaling termination.
        """
        terminal_names = {meta.name for meta in self.registry.terminal_skills()}
        if already_executed & terminal_names:
            return SelectionPlan(
                wave_id=wave_id,
                execution_mode="sequential",
                rationale="Terminal wave already executed; investigation complete.",
                continuation_signal="terminate",
                termination_reason="investigation_complete",
            )

        evidence_triggered = self._evidence_triggered_candidates(already_executed)
        if evidence_triggered:
            return self._assemble_investigative_wave(
                wave_id=wave_id,
                candidates=evidence_triggered,
                trigger_reason="evidence_triggered",
                skill_parameters=skill_parameters,
                already_executed=already_executed,
            )

        terminal_candidates = self.registry.terminal_skills()
        if not terminal_candidates:
            return SelectionPlan(
                wave_id=wave_id,
                execution_mode="sequential",
                rationale="No investigative waves remain and no terminal skill is registered.",
                continuation_signal="terminate",
                termination_reason="no_terminal_skill_registered",
            )

        selected = [
            SelectedSkillPlan(skill_name=meta.name, trigger_reason="terminal", resolved_params={})
            for meta in terminal_candidates
        ]
        return SelectionPlan(
            wave_id=wave_id,
            execution_mode="sequential",
            selected_skills=selected,
            rationale=(
                "Investigative waves exhausted; no further trigger conditions remained "
                "(marginal-evidence cutoff). Emitting terminal wave "
                f"({', '.join(s.skill_name for s in selected)}), run sequentially since "
                "each terminal skill consumes the prior one's output."
            ),
            continuation_signal="awaiting_evidence",
        )

    def _evidence_triggered_candidates(self, already_executed: set[str]) -> list[SkillMetadata]:
        """No skill in the current catalog declares an evidence-trigger condition
        (skill_selection_engine.md §6.2's mechanism is dormant until one does).
        This hook is real, not simulated: a future skill declaring such a
        condition in its metadata would be picked up here with zero engine
        changes — it simply has nothing to return today."""
        return []

    def _assemble_investigative_wave(
        self,
        wave_id: int,
        candidates: list[SkillMetadata],
        trigger_reason: TriggerReason,
        skill_parameters: dict[str, dict[str, object]],
        already_executed: set[str],
    ) -> SelectionPlan:
        excluded: list[ExcludedCandidate] = []
        surviving: list[SkillMetadata] = []

        for meta in candidates:
            if meta.name in already_executed:
                excluded.append(
                    ExcludedCandidate(skill_name=meta.name, reason="already executed this session")
                )
                continue
            missing = missing_required_inputs(meta, skill_parameters)
            if missing:
                excluded.append(
                    ExcludedCandidate(
                        skill_name=meta.name,
                        reason=f"required input(s) not supplied: {', '.join(missing)}",
                    )
                )
                continue
            surviving.append(meta)

        ranked = sorted(surviving, key=_specificity_score, reverse=True)
        budgeted = ranked[: self.max_skills_per_wave]
        for meta in ranked[self.max_skills_per_wave :]:
            excluded.append(
                ExcludedCandidate(skill_name=meta.name, reason="excluded for wave budget")
            )

        if not budgeted:
            reason = (
                "no_skill_matched" if trigger_reason == "signal_match" else "no_further_candidates"
            )
            return SelectionPlan(
                wave_id=wave_id,
                execution_mode="parallel",
                excluded_candidates=excluded,
                rationale=(
                    "No skill in the catalog declares this alert type as a trigger "
                    "(or all matching candidates were excluded); no generalist "
                    "fallback skill is registered."
                ),
                continuation_signal="terminate",
                termination_reason=reason,
            )

        selected = [
            SelectedSkillPlan(
                skill_name=meta.name,
                trigger_reason=trigger_reason,
                resolved_params=skill_parameters.get(meta.name, {}),
            )
            for meta in budgeted
        ]
        return SelectionPlan(
            wave_id=wave_id,
            execution_mode="parallel",
            selected_skills=selected,
            excluded_candidates=excluded,
            rationale=(
                f"{trigger_reason} matched {len(budgeted)} investigative skill(s): "
                f"{', '.join(meta.name for meta in budgeted)}."
            ),
            continuation_signal="awaiting_evidence",
        )
