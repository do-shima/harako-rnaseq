from __future__ import annotations

import pytest

from app.analysis_eligibility import (
    AnalysisPlanError,
    analysis_plan_from_rows,
    assert_analysis_plan_consistent,
    evaluate_analysis_eligibility,
)


def row(sample: str, condition: str) -> dict[str, str]:
    return {
        "sample": sample,
        "condition": condition,
        "fastq1": f"{sample}.fastq.gz" if sample else "",
        "fastq2": "",
    }


@pytest.mark.parametrize(
    ("rows", "mode", "reason", "counts"),
    [
        ([], "invalid", "no_samples", {}),
        ([row("", "A")], "invalid", "missing_sample", {}),
        ([row("s1", "")], "invalid", "missing_condition", {}),
        ([row("s1", "A"), row("s1", "A")], "invalid", "duplicate_sample", {}),
        ([row("s1", "A")], "qc_only", "single_condition", {"A": 1}),
        ([row("s1", "A"), row("s2", "A")], "qc_only", "single_condition", {"A": 2}),
        (
            [row("a1", "A"), row("b1", "B")],
            "qc_only",
            "insufficient_replicates",
            {"A": 1, "B": 1},
        ),
        (
            [row("a1", "A"), row("b1", "B"), row("b2", "B")],
            "qc_only",
            "insufficient_replicates",
            {"A": 1, "B": 2},
        ),
        (
            [row("a1", "A"), row("a2", "A"), row("b1", "B"), row("b2", "B")],
            "differential",
            "eligible",
            {"A": 2, "B": 2},
        ),
        (
            [
                row("a1", "A"),
                row("a2", "A"),
                row("a3", "A"),
                row("b1", "B"),
                row("b2", "B"),
            ],
            "differential",
            "eligible",
            {"A": 3, "B": 2},
        ),
        (
            [
                row("a1", "A"),
                row("a2", "A"),
                row("b1", "B"),
                row("b2", "B"),
                row("c1", "C"),
                row("c2", "C"),
            ],
            "differential",
            "eligible",
            {"A": 2, "B": 2, "C": 2},
        ),
        (
            [
                row("a1", "A"),
                row("a2", "A"),
                row("b1", "B"),
                row("b2", "B"),
                row("c1", "C"),
            ],
            "qc_only",
            "insufficient_replicates",
            {"A": 2, "B": 2, "C": 1},
        ),
    ],
)
def test_policy_matrix(rows, mode, reason, counts):
    result = evaluate_analysis_eligibility(rows)
    assert result.mode == mode
    assert result.reason_code == reason
    assert result.condition_counts == counts
    assert result.eligible_for_de is (mode == "differential")
    assert result.structurally_valid is (mode != "invalid")


def test_empty_editor_rows_are_ignored():
    result = evaluate_analysis_eligibility(
        [
            {"sample": "", "condition": "", "fastq1": "", "fastq2": ""},
            row("a1", "A"),
        ]
    )
    assert result.mode == "qc_only"
    assert result.total_samples == 1


def test_result_is_independent_of_row_order_and_counts_are_sorted():
    rows = [row("z1", "Z"), row("a1", "A"), row("z2", "Z"), row("a2", "A")]
    forward = evaluate_analysis_eligibility(rows)
    reverse = evaluate_analysis_eligibility(list(reversed(rows)))
    assert forward == reverse
    assert list(forward.condition_counts) == ["A", "Z"]


def test_plan_round_trip_and_mismatch_detection():
    rows = [row("a1", "A"), row("a2", "A")]
    plan = analysis_plan_from_rows(rows)
    assert plan == {
        "schema_version": 1,
        "policy_version": 1,
        "mode": "qc_only",
        "structurally_valid": True,
        "eligible_for_de": False,
        "reason_code": "single_condition",
        "condition_counts": {"A": 2},
        "total_samples": 2,
        "contrast_allowed": False,
        "enrichment_allowed": False,
    }
    assert_analysis_plan_consistent(plan, rows)
    with pytest.raises(AnalysisPlanError, match="condition_counts"):
        assert_analysis_plan_consistent(plan, [row("a1", "A")])


def test_invalid_rows_do_not_produce_executable_plan():
    with pytest.raises(AnalysisPlanError, match="missing_condition"):
        analysis_plan_from_rows([row("s1", "")])
