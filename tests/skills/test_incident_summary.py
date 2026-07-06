from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
for _skill in (
    "incident_summary",
    "root_cause_prioritization",
    "data_drift_analysis",
    "model_performance_analysis",
):
    sys.path.insert(0, str(_SKILLS_DIR / _skill / "scripts"))

import _incident_summary_core as core  # noqa: E402
from run_data_drift_analysis import run as run_data_drift_analysis  # noqa: E402
from run_incident_summary import IncidentSummaryInput, run  # noqa: E402
from run_model_performance_analysis import run as run_model_performance_analysis  # noqa: E402
from run_root_cause_prioritization import run as run_root_cause_prioritization  # noqa: E402

from shared.schemas.finding import (  # noqa: E402
    ActionItem,
    EvidenceItem,
    Finding,
    HypothesisCandidate,
    TimeWindow,
)

_WINDOW = TimeWindow(start=datetime.now(UTC), end=datetime.now(UTC))
_DETECTED_AT = datetime.now(UTC)


def _upstream_finding() -> Finding:
    return Finding(
        investigation_summary="synthetic upstream finding",
        evidence=[
            EvidenceItem(
                evidence_id="metric_x",
                subject="metric_x",
                metric="value",
                value=42.0,
                baseline=10.0,
                time_window=_WINDOW,
                source_skill="upstream_skill",
            )
        ],
        possible_root_causes=[],
        confidence_score=0.9,
        recommended_actions=[],
        preventive_actions=["Prevent recurrence of X"],
        limitations=[],
    )


def _root_cause_finding(
    confidence_score: float, cause_evidence_ref: str = "upstream_skill::metric_x"
) -> Finding:
    return Finding(
        investigation_summary="synthetic ranking",
        evidence=[],
        possible_root_causes=[
            HypothesisCandidate(
                cause="Synthetic root cause",
                supporting_evidence=[cause_evidence_ref],
                conflicting_evidence=[],
                local_confidence=confidence_score,
            )
        ],
        confidence_score=confidence_score,
        recommended_actions=[
            ActionItem(
                description="Do the fix",
                risk_tier="requires_approval",
                justifying_finding_refs=[cause_evidence_ref],
                time_horizon="immediate",
            )
        ],
        preventive_actions=["Add a regression test"],
        limitations=[],
    )


def test_compute_confidence_none_finding_is_low() -> None:
    score, band = core.compute_confidence(None)
    assert band == "low"
    assert score < 0.5


def test_compute_confidence_empty_hypotheses_is_low() -> None:
    empty = _root_cause_finding(0.9)
    empty.possible_root_causes = []
    _, band = core.compute_confidence(empty)
    assert band == "low"


def test_compute_confidence_high_when_upstream_confidence_high() -> None:
    score, band = core.compute_confidence(_root_cause_finding(0.9))
    assert band == "high"
    assert score >= 0.8


def test_compute_confidence_medium_when_upstream_confidence_medium() -> None:
    _, band = core.compute_confidence(_root_cause_finding(0.6))
    assert band == "medium"


def test_resolve_cited_evidence_follows_qualified_refs() -> None:
    findings = {"upstream_skill": _upstream_finding()}
    root_cause = _root_cause_finding(0.9, cause_evidence_ref="upstream_skill::metric_x")

    cited = core.resolve_cited_evidence(root_cause, findings)

    assert len(cited) == 1
    assert cited[0].subject == "metric_x"


def test_resolve_cited_evidence_skips_unresolvable_refs() -> None:
    findings = {"upstream_skill": _upstream_finding()}
    root_cause = _root_cause_finding(0.9, cause_evidence_ref="upstream_skill::does_not_exist")

    cited = core.resolve_cited_evidence(root_cause, findings)

    assert cited == []


def test_validate_sections_flags_empty_sections() -> None:
    sections = core.IncidentReportSections(
        executive_summary="ok",
        observed_symptoms="ok",
        root_cause_analysis="",
        evidence_citations="",
        remediation_actions="ok",
        preventive_recommendations="ok",
    )
    limitations = core.validate_sections(sections)

    assert len(limitations) == 2
    assert any("Root Cause Analysis" in limitation for limitation in limitations)


def test_render_report_markdown_contains_all_section_headers() -> None:
    sections = core.IncidentReportSections(
        executive_summary="a",
        observed_symptoms="b",
        root_cause_analysis="c",
        evidence_citations="d",
        remediation_actions="e",
        preventive_recommendations="f",
    )
    report = core.render_report_markdown("INC-1", sections, 0.92, "high")

    for header in (
        "# Incident Report: INC-1",
        "## Executive Summary",
        "## Observed Symptoms",
        "## Root Cause Analysis",
        "## Evidence Citations",
        "## Remediation Actions",
        "## Preventive Recommendations",
    ):
        assert header in report


def test_run_incident_summary_core_missing_root_cause_finding() -> None:
    result = core.run_incident_summary(
        incident_id="INC-1",
        alert_type="DownstreamAccuracyDrop",
        affected_system="Fraud_Detection_XGBoost",
        detected_at=_DETECTED_AT,
        findings={"upstream_skill": _upstream_finding()},
    )

    assert result.confidence_band == "low"
    assert any("root cause is undetermined" in limitation for limitation in result.limitations)
    assert "could not be determined" in result.sections.executive_summary


def test_incident_summary_input_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        IncidentSummaryInput.model_validate(
            {
                "incident_id": "INC-1",
                "alert_type": "x",
                "affected_system": "y",
                "detected_at": _DETECTED_AT,
                "findings": {},
                "unexpected_field": "boom",
            }
        )


async def test_run_produces_finding_with_markdown_report() -> None:
    findings = {
        "upstream_skill": _upstream_finding(),
        "root_cause_prioritization": _root_cause_finding(0.9),
    }
    finding = await run(
        incident_id="INC-1",
        alert_type="DownstreamAccuracyDrop",
        affected_system="Fraud_Detection_XGBoost",
        detected_at=_DETECTED_AT,
        findings=findings,
    )

    assert finding.confidence_score >= 0.8
    assert "# Incident Report: INC-1" in finding.investigation_summary
    assert len(finding.evidence) == 1
    assert len(finding.possible_root_causes) == 1
    assert len(finding.recommended_actions) == 1
    assert "Add a regression test" in finding.preventive_actions


async def test_run_end_to_end_full_four_skill_pipeline() -> None:
    drift_finding = await run_data_drift_analysis(
        reference_dataset_id="fraud_detection_xgboost",
        current_dataset_id="fraud_detection_xgboost",
        numerical_features=["transaction_amount"],
        categorical_features=["user_zipcode", "device_type"],
        min_sample_size=100,
    )
    performance_finding = await run_model_performance_analysis(
        predictions_dataset_id="fraud_detection_xgboost"
    )
    ranking_finding = await run_root_cause_prioritization(
        findings={
            "data_drift_analysis": drift_finding,
            "model_performance_analysis": performance_finding,
        }
    )

    report_finding = await run(
        incident_id="INC-FRAUD-001",
        alert_type="DownstreamAccuracyDrop",
        affected_system="Fraud_Detection_XGBoost",
        detected_at=_DETECTED_AT,
        findings={
            "data_drift_analysis": drift_finding,
            "model_performance_analysis": performance_finding,
            "root_cause_prioritization": ranking_finding,
        },
    )

    report_md = report_finding.investigation_summary
    assert "# Incident Report: INC-FRAUD-001" in report_md
    assert "user_zipcode" in report_md
    assert report_finding.confidence_score > 0.0
    assert len(report_finding.possible_root_causes) >= 2
    assert len(report_finding.evidence) >= 1
