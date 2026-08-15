"""Backward-compatible imports for analysis eligibility policy."""

from app.core.analysis import (
    PLAN_SCHEMA_VERSION,
    POLICY_VERSION,
    AnalysisEligibility,
    AnalysisPlanError,
    Mode,
    analysis_plan_from_rows,
    assert_analysis_plan_consistent,
    evaluate_analysis_eligibility,
    resolve_analysis_plan,
)


__all__ = [
    "PLAN_SCHEMA_VERSION",
    "POLICY_VERSION",
    "AnalysisEligibility",
    "AnalysisPlanError",
    "Mode",
    "analysis_plan_from_rows",
    "assert_analysis_plan_consistent",
    "evaluate_analysis_eligibility",
    "resolve_analysis_plan",
]
