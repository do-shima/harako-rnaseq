"""Policy-versioned analysis eligibility and plan consistency."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Mapping, Sequence


POLICY_VERSION = 1
PLAN_SCHEMA_VERSION = 1
Mode = Literal["differential", "qc_only", "invalid"]


class AnalysisPlanError(ValueError):
    pass


@dataclass(frozen=True)
class AnalysisEligibility:
    structurally_valid: bool
    eligible_for_de: bool
    mode: Mode
    reason_code: str
    condition_counts: dict[str, int]
    total_samples: int
    contrast_allowed: bool
    enrichment_allowed: bool
    policy_version: int = POLICY_VERSION

    def to_plan(self) -> dict[str, object]:
        plan = asdict(self)
        plan["schema_version"] = PLAN_SCHEMA_VERSION
        return {
            "schema_version": plan["schema_version"],
            "policy_version": plan["policy_version"],
            "mode": plan["mode"],
            "structurally_valid": plan["structurally_valid"],
            "eligible_for_de": plan["eligible_for_de"],
            "reason_code": plan["reason_code"],
            "condition_counts": plan["condition_counts"],
            "total_samples": plan["total_samples"],
            "contrast_allowed": plan["contrast_allowed"],
            "enrichment_allowed": plan["enrichment_allowed"],
        }


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_empty_editor_row(row: Mapping[str, object]) -> bool:
    return not any(_text(row.get(key)) for key in ("sample", "condition", "fastq1", "fastq2"))


def _result(
    *,
    structurally_valid: bool,
    eligible_for_de: bool,
    mode: Mode,
    reason_code: str,
    condition_counts: Mapping[str, int],
    total_samples: int,
) -> AnalysisEligibility:
    counts = {key: int(condition_counts[key]) for key in sorted(condition_counts)}
    return AnalysisEligibility(
        structurally_valid=structurally_valid,
        eligible_for_de=eligible_for_de,
        mode=mode,
        reason_code=reason_code,
        condition_counts=counts,
        total_samples=int(total_samples),
        contrast_allowed=eligible_for_de,
        enrichment_allowed=eligible_for_de,
    )


def evaluate_analysis_eligibility(
    sample_rows: Sequence[Mapping[str, object]],
) -> AnalysisEligibility:
    rows = [row for row in sample_rows if not _is_empty_editor_row(row)]
    if not rows:
        return _result(
            structurally_valid=False,
            eligible_for_de=False,
            mode="invalid",
            reason_code="no_samples",
            condition_counts={},
            total_samples=0,
        )

    samples = [_text(row.get("sample")) for row in rows]
    conditions = [_text(row.get("condition")) for row in rows]
    if any(not sample for sample in samples):
        return _result(
            structurally_valid=False,
            eligible_for_de=False,
            mode="invalid",
            reason_code="missing_sample",
            condition_counts={},
            total_samples=len({sample for sample in samples if sample}),
        )
    if any(not condition for condition in conditions):
        counts: dict[str, int] = {}
        for condition in conditions:
            if condition:
                counts[condition] = counts.get(condition, 0) + 1
        return _result(
            structurally_valid=False,
            eligible_for_de=False,
            mode="invalid",
            reason_code="missing_condition",
            condition_counts=counts,
            total_samples=len(set(samples)),
        )
    if len(set(samples)) != len(samples):
        return _result(
            structurally_valid=False,
            eligible_for_de=False,
            mode="invalid",
            reason_code="duplicate_sample",
            condition_counts={},
            total_samples=len(set(samples)),
        )

    counts: dict[str, int] = {}
    for condition in conditions:
        counts[condition] = counts.get(condition, 0) + 1
    if len(counts) < 2:
        return _result(
            structurally_valid=True,
            eligible_for_de=False,
            mode="qc_only",
            reason_code="single_condition",
            condition_counts=counts,
            total_samples=len(samples),
        )
    if any(count < 2 for count in counts.values()):
        return _result(
            structurally_valid=True,
            eligible_for_de=False,
            mode="qc_only",
            reason_code="insufficient_replicates",
            condition_counts=counts,
            total_samples=len(samples),
        )
    return _result(
        structurally_valid=True,
        eligible_for_de=True,
        mode="differential",
        reason_code="eligible",
        condition_counts=counts,
        total_samples=len(samples),
    )


def analysis_plan_from_rows(
    sample_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    eligibility = evaluate_analysis_eligibility(sample_rows)
    if not eligibility.structurally_valid:
        raise AnalysisPlanError(f"Cannot create analysis_plan for invalid sample rows: {eligibility.reason_code}")
    return eligibility.to_plan()


def assert_analysis_plan_consistent(
    plan: Mapping[str, object],
    sample_rows: Sequence[Mapping[str, object]],
) -> AnalysisEligibility:
    actual = evaluate_analysis_eligibility(sample_rows)
    expected_counts = {str(key): int(value) for key, value in dict(plan.get("condition_counts") or {}).items()}
    mismatches: list[str] = []
    expected_fields = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "mode": actual.mode,
        "structurally_valid": actual.structurally_valid,
        "eligible_for_de": actual.eligible_for_de,
        "reason_code": actual.reason_code,
        "condition_counts": actual.condition_counts,
        "total_samples": actual.total_samples,
        "contrast_allowed": actual.contrast_allowed,
        "enrichment_allowed": actual.enrichment_allowed,
    }
    for key, actual_value in expected_fields.items():
        configured_value = expected_counts if key == "condition_counts" else plan.get(key)
        if configured_value != actual_value:
            mismatches.append(f"{key}: frozen={configured_value!r}, actual={actual_value!r}")
    if mismatches:
        raise AnalysisPlanError(
            "Frozen analysis_plan does not match the frozen sample table: " + "; ".join(mismatches)
        )
    return actual


def resolve_analysis_plan(
    configured_plan: Mapping[str, object] | None,
    sample_rows: Sequence[Mapping[str, object]],
    *,
    legacy_frozen: bool = False,
) -> tuple[dict[str, object], bool]:
    if configured_plan:
        assert_analysis_plan_consistent(configured_plan, sample_rows)
        return dict(configured_plan), False
    eligibility = evaluate_analysis_eligibility(sample_rows)
    if not eligibility.structurally_valid:
        raise AnalysisPlanError(f"Sample table is structurally invalid: {eligibility.reason_code}")
    if legacy_frozen and not eligibility.eligible_for_de:
        raise AnalysisPlanError(
            "Legacy frozen run is not eligible for differential expression under policy version 1. "
            "Create a new QC-only run; the existing run was not modified."
        )
    return eligibility.to_plan(), legacy_frozen
