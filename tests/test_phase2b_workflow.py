from __future__ import annotations

import importlib.util
import html
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.analysis_eligibility import analysis_plan_from_rows
from scripts.check_r_integration_stack import HOST_SKIP_REASON, r_integration_stack


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
SNAKEMAKE_AVAILABLE = importlib.util.find_spec("snakemake") is not None
REAL_R_STACK_AVAILABLE = r_integration_stack().available


def make_rows(counts: dict[str, int]) -> list[dict[str, str]]:
    rows = []
    for condition, count in counts.items():
        for index in range(1, count + 1):
            rows.append(
                {
                    "sample": f"{condition}{index}",
                    "condition": condition,
                    "fastq1": "sample2.fastq",
                    "fastq2": "",
                }
            )
    return rows


def write_samples(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "sample\tcondition\tfastq1\n"
        + "".join(
            f"{row['sample']}\t{row['condition']}\t{row['fastq1']}\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def write_counts(path: Path, rows: list[dict[str, str]], *, all_zero: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = [row["sample"] for row in rows]
    lines = ["gene_id\t" + "\t".join(samples)]
    variability = (0.3, 0.55, 0.8, 1.1, 1.6, 2.5, 4.0)
    for gene_index in range(1, 201):
        values = []
        for sample_index, row in enumerate(rows):
            if all_zero:
                value = 0
            else:
                base = 40 + gene_index * 4
                condition_factor = (
                    2.2
                    if row["condition"] == "B" and gene_index <= 50
                    else (0.45 if row["condition"] == "B" and gene_index <= 90 else 1.0)
                )
                if sample_index % 2 == 0:
                    replicate_factor = 1.0
                else:
                    replicate_factor = variability[gene_index % len(variability)]
                value = max(1, round(base * condition_factor * replicate_factor))
            values.append(str(value))
        lines.append(f"gene{gene_index}\t" + "\t".join(values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.skipif(not SNAKEMAKE_AVAILABLE, reason="Snakemake is validated in Docker")
@pytest.mark.parametrize(
    ("counts", "expected_mode", "expect_enrichment"),
    [
        ({"A": 1}, "qc_only", False),
        ({"A": 2}, "qc_only", False),
        ({"A": 1, "B": 1}, "qc_only", False),
        ({"A": 2, "B": 2}, "differential", True),
    ],
)
def test_main_dag_respects_analysis_plan(tmp_path, counts, expected_mode, expect_enrichment):
    rows = make_rows(counts)
    plan = analysis_plan_from_rows(rows)
    assert plan["mode"] == expected_mode
    samples = tmp_path / "metadata" / "samples.tsv"
    write_samples(samples, rows)
    out = tmp_path / "out"
    config = {
        "engine": "real",
        "species": "mouse",
        "samples": [row["sample"] for row in rows],
        "input": str(DATA),
        "output": str(out),
        "sample_table": str(samples),
        "ref": {
            "transcripts_fasta": str(DATA / "transcripts.fa"),
            "genome_fasta": str(DATA / "genome.fa"),
            "gtf": str(DATA / "genes.gtf"),
        },
        "analysis_plan": plan,
        "enrichment": {"enable": True},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "snakemake",
            "-s",
            str(ROOT / "workflow" / "Snakefile"),
            "--configfile",
            str(config_path),
            "--cores",
            "1",
            "-n",
            "-p",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert f"mode={expected_mode}" in output
    assert "deseq2/status.json" in output
    assert ("rule enrichment" in output) is expect_enrichment


@pytest.mark.skipif(not SNAKEMAKE_AVAILABLE, reason="Snakemake is validated in Docker")
@pytest.mark.skipif(not REAL_R_STACK_AVAILABLE, reason=HOST_SKIP_REASON)
@pytest.mark.parametrize(
    ("counts", "expected_mode"),
    [
        ({"A": 1}, "qc_only"),
        ({"A": 2}, "qc_only"),
        ({"A": 1, "B": 1}, "qc_only"),
        ({"A": 2, "B": 2}, "differential"),
    ],
)
def test_real_deseq2_fixture_modes(tmp_path, counts, expected_mode):
    rows = make_rows(counts)
    samples = tmp_path / "samples.tsv"
    counts_path = tmp_path / "counts.tsv"
    out = tmp_path / "out"
    write_samples(samples, rows)
    write_counts(counts_path, rows)
    config = {
        "output": str(out),
        "counts": str(counts_path),
        "sample_table": str(samples),
        "analysis_plan": analysis_plan_from_rows(rows),
        "contrasts": ["B_vs_A"] if expected_mode == "differential" else [],
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "snakemake",
            "-s",
            str(ROOT / "tests" / "deseq2_fixture" / "Snakefile"),
            "--configfile",
            str(config_path),
            "--cores",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    status = json.loads((out / "deseq2" / "status.json").read_text(encoding="utf-8"))
    assert status["mode"] == expected_mode
    lines = (out / "deseq2" / "results.tsv").read_text(encoding="utf-8").splitlines()
    if expected_mode == "qc_only":
        assert len(lines) == 1
        assert status["differential_results_available"] is False
    else:
        assert len(lines) > 1
        assert status["differential_results_available"] is True
    if len(rows) == 1:
        assert status["pca_available"] is False
        assert status["sample_distance_available"] is False
    report_path = out / "report" / "report.html"
    report_text = report_path.read_text(encoding="utf-8")
    visible_report_text = re.sub(
        r"\s+",
        " ",
        html.unescape(re.sub(r"<[^>]+>", " ", report_text)),
    )
    assert str(tmp_path) not in report_text
    if expected_mode == "qc_only":
        assert "QC-only analysis" in visible_report_text
        assert (
            "inferential differential-expression analysis was not performed"
            in visible_report_text
        )
        assert (
            "enrichment was not run because inferential DE was unavailable"
            in visible_report_text
        )
    else:
        assert "Differential-expression analysis" not in report_text or "DESeq2 results" in report_text
        assert "gene1" in report_text
    selfcontained = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_report_selfcontained.py"),
            "--report",
            str(report_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert selfcontained.returncode == 0, selfcontained.stdout + selfcontained.stderr


@pytest.mark.skipif(not SNAKEMAKE_AVAILABLE, reason="Snakemake is validated in Docker")
@pytest.mark.skipif(not REAL_R_STACK_AVAILABLE, reason=HOST_SKIP_REASON)
def test_real_deseq2_all_zero_fails_clearly(tmp_path):
    rows = make_rows({"A": 1})
    samples = tmp_path / "samples.tsv"
    counts_path = tmp_path / "counts.tsv"
    write_samples(samples, rows)
    write_counts(counts_path, rows, all_zero=True)
    config = {
        "output": str(tmp_path / "out"),
        "counts": str(counts_path),
        "sample_table": str(samples),
        "analysis_plan": analysis_plan_from_rows(rows),
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "snakemake",
            "-s",
            str(ROOT / "tests" / "deseq2_fixture" / "Snakefile"),
            "--configfile",
            str(config_path),
            "--cores",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "count matrix is all zero" in (result.stdout + result.stderr)
