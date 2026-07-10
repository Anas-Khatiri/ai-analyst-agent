from __future__ import annotations

from datetime import UTC, datetime

import _data_drift_analysis_core as core
from pydantic import BaseModel, ConfigDict, Field

from domain.finding import (
    ActionItem,
    EvidenceItem,
    Finding,
    HypothesisCandidate,
    TimeWindow,
)
from infra.tools import dataset_access

SKILL_NAME = "data_drift_analysis"


class DataDriftAnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_dataset_id: str
    current_dataset_id: str
    numerical_features: list[str]
    categorical_features: list[str] = Field(default_factory=list)
    target_column: str | None = None
    p_value_threshold: float = core.DEFAULT_P_VALUE_THRESHOLD
    min_sample_size: int = 100


def _build_evidence(result: core.DriftComputationResult, window: TimeWindow) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    for feature in result.feature_results:
        evidence.append(
            EvidenceItem(
                evidence_id=f"{feature.feature_name}_null_rate",
                subject=feature.feature_name,
                metric="null_rate",
                value=feature.null_rate_current,
                baseline=feature.null_rate_reference,
                time_window=window,
                source_skill=SKILL_NAME,
            )
        )
        evidence.append(
            EvidenceItem(
                evidence_id=f"{feature.feature_name}_{feature.test_name}",
                subject=feature.feature_name,
                metric=f"{feature.test_name}_p_value",
                value=feature.p_value,
                baseline=None,
                time_window=window,
                source_skill=SKILL_NAME,
            )
        )
        evidence.append(
            EvidenceItem(
                evidence_id=f"{feature.feature_name}_psi",
                subject=feature.feature_name,
                metric="psi",
                value=feature.psi,
                baseline=None,
                time_window=window,
                source_skill=SKILL_NAME,
            )
        )
    return evidence


def _build_hypotheses(result: core.DriftComputationResult) -> list[HypothesisCandidate]:
    hypotheses: list[HypothesisCandidate] = []
    for feature in result.feature_results:
        if not feature.drifted:
            continue
        if feature.null_rate_spike:
            hypotheses.append(
                HypothesisCandidate(
                    cause=(
                        f"Upstream pipeline failure causing missing values in "
                        f"'{feature.feature_name}' (null rate "
                        f"{feature.null_rate_reference:.4f} -> {feature.null_rate_current:.4f})."
                    ),
                    supporting_evidence=[f"{feature.feature_name}_null_rate"],
                    local_confidence=result.confidence_score,
                )
            )
        else:
            hypotheses.append(
                HypothesisCandidate(
                    cause=(
                        f"Organic distribution shift in '{feature.feature_name}' "
                        f"(PSI={feature.psi:.4f}, {feature.test_name} p={feature.p_value:.6f})."
                    ),
                    supporting_evidence=[
                        f"{feature.feature_name}_psi",
                        f"{feature.feature_name}_{feature.test_name}",
                    ],
                    local_confidence=result.confidence_score,
                )
            )
    return hypotheses


def _build_actions(result: core.DriftComputationResult) -> tuple[list[ActionItem], list[str]]:
    actions: list[ActionItem] = []
    preventive: list[str] = []
    for feature in result.feature_results:
        if feature.null_rate_spike:
            actions.append(
                ActionItem(
                    description=(
                        f"Deploy default imputation for null '{feature.feature_name}' values."
                    ),
                    risk_tier="auto_executable",
                    justifying_finding_refs=[f"{feature.feature_name}_null_rate"],
                    time_horizon="immediate",
                )
            )
            preventive.append(
                f"Add a schema validation gate rejecting inference batches with "
                f">1% missing values on '{feature.feature_name}'."
            )
        elif feature.drifted:
            actions.append(
                ActionItem(
                    description=(
                        f"Schedule a retraining run incorporating the drifted "
                        f"'{feature.feature_name}' distribution."
                    ),
                    risk_tier="requires_approval",
                    justifying_finding_refs=[f"{feature.feature_name}_psi"],
                    time_horizon="medium_term",
                )
            )
    return actions, preventive


async def run(**params: object) -> Finding:
    """Entrypoint contract per DYNAMIC_DISCOVERY_DESIGN.md §3.3: a module-level `run()`."""
    validated = DataDriftAnalysisInput.model_validate(params)

    reference = await dataset_access.load_reference_dataset(validated.reference_dataset_id)
    current = await dataset_access.load_current_dataset(validated.current_dataset_id)

    result = core.run_drift_analysis(
        reference=reference,
        current=current,
        numerical_features=validated.numerical_features,
        categorical_features=validated.categorical_features,
        p_value_threshold=validated.p_value_threshold,
        min_sample_size=validated.min_sample_size,
    )

    now = datetime.now(UTC)
    window = TimeWindow(start=now, end=now)
    actions, preventive_actions = _build_actions(result)
    drifted_features = [f.feature_name for f in result.feature_results if f.drifted]
    summary = (
        f"Dataset drift {'detected' if result.dataset_drift_detected else 'not detected'} "
        f"across {len(result.feature_results)} feature(s); "
        f"{len(drifted_features)} drifted: {', '.join(drifted_features) or 'none'}."
    )

    return Finding(
        investigation_summary=summary,
        evidence=_build_evidence(result, window),
        possible_root_causes=_build_hypotheses(result),
        confidence_score=result.confidence_score,
        recommended_actions=actions,
        preventive_actions=preventive_actions,
        limitations=result.limitations,
    )
