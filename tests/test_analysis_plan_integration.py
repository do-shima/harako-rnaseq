from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import yaml

from app.analysis_eligibility import analysis_plan_from_rows
from app.ui.config_builder import build_config_payload
from app.ui import run as ui_run


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"


def rows_for(counts: dict[str, int]) -> list[dict[str, str]]:
    rows = []
    for condition, count in counts.items():
        for index in range(1, count + 1):
            sample = f"{condition}{index}"
            rows.append(
                {
                    "sample": sample,
                    "condition": condition,
                    "fastq1": "sample2.fastq",
                    "fastq2": "",
                }
            )
    return rows


def base_payload(rows: list[dict[str, str]]) -> dict[str, object]:
    plan = analysis_plan_from_rows(rows)
    return build_config_payload(
        project_name="plan-test",
        engine="stub",
        species="mouse",
        samples=[row["sample"] for row in rows],
        input_root=str(DATA),
        output_root="/output",
        sample_table="/output/metadata/samples.tsv",
        threads=1,
        ref_mode="fasta_gtf",
        ref_block={
            "transcripts_fasta": "transcripts.fa",
            "genome_fasta": "genome.fa",
            "gtf": "genes.gtf",
        },
        ref_preset="",
        ref_release="",
        ref_cache_dir="",
        use_custom_refs=True,
        analysis_plan=plan,
    )


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


def test_config_manifest_and_frozen_config_share_analysis_plan(tmp_path):
    rows = rows_for({"A": 1, "B": 1})
    payload = base_payload(rows)
    plan = payload["analysis_plan"]
    assert plan["mode"] == "qc_only"

    manifest = ui_run.build_manifest_payload(
        payload,
        rows,
        ["sample2.fastq"],
        lambda value: value,
        "test-rev",
        DATA,
    )
    changed = copy.deepcopy(manifest)
    changed["config"]["analysis_plan"]["mode"] = "differential"
    assert ui_run.manifest_run_id(manifest) != ui_run.manifest_run_id(changed)

    samples = tmp_path / "session" / "samples.tsv"
    write_samples(samples, rows)
    frozen_path = ui_run.write_frozen_run_config(
        tmp_path / "run",
        payload,
        sample_table_source=samples,
    )
    frozen = yaml.safe_load(frozen_path.read_text(encoding="utf-8"))
    assert frozen["analysis_plan"] == plan


def test_legacy_eligible_run_uses_transient_plan_without_rewrite(tmp_path):
    rows = rows_for({"A": 2, "B": 2})
    config_path = tmp_path / "run" / "config_resolved.yaml"
    samples_path = tmp_path / "run" / "metadata" / "samples.tsv"
    write_samples(samples_path, rows)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump({"sample_table": str(samples_path)}, sort_keys=False),
        encoding="utf-8",
    )
    before = config_path.read_bytes()

    result = ui_run.assess_frozen_analysis_plan(config_path)

    assert result["resume_allowed"] is True
    assert result["legacy"] is True
    assert result["plan"]["mode"] == "differential"
    assert config_path.read_bytes() == before


def test_legacy_ineligible_run_is_blocked_without_rewrite(tmp_path):
    rows = rows_for({"A": 1})
    config_path = tmp_path / "run" / "config_resolved.yaml"
    samples_path = tmp_path / "run" / "metadata" / "samples.tsv"
    write_samples(samples_path, rows)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump({"sample_table": str(samples_path)}, sort_keys=False),
        encoding="utf-8",
    )
    before = config_path.read_bytes()

    result = ui_run.assess_frozen_analysis_plan(config_path)

    assert result["resume_allowed"] is False
    assert result["legacy"] is True
    assert "Create a new QC-only run" in result["error"]
    assert config_path.read_bytes() == before


def test_frozen_plan_mismatch_blocks_resume(tmp_path):
    rows = rows_for({"A": 2, "B": 2})
    config_path = tmp_path / "run" / "config_resolved.yaml"
    samples_path = tmp_path / "run" / "metadata" / "samples.tsv"
    write_samples(samples_path, rows)
    bad_plan = analysis_plan_from_rows(rows)
    bad_plan["condition_counts"] = {"A": 1, "B": 1}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(
            {"sample_table": str(samples_path), "analysis_plan": bad_plan},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = ui_run.assess_frozen_analysis_plan(config_path)
    assert result["resume_allowed"] is False
    assert "does not match" in result["error"]


def test_cli_validate_accepts_qc_only_and_reports_plan(tmp_path):
    rows = rows_for({"A": 1})
    samples_path = tmp_path / "samples.tsv"
    write_samples(samples_path, rows)
    config = base_payload(rows)
    config["sample_table"] = str(samples_path)
    config["input"] = str(DATA)
    config["output"] = str(tmp_path / "output")
    config["enrichment"] = {"enable": True}
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app",
            "validate",
            "--config",
            str(config_path),
            "--input",
            str(DATA),
            "--output",
            str(tmp_path / "output"),
            "--skip-toolcheck",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Analysis mode: qc_only" in result.stdout
    assert "Condition counts: A=1" in result.stdout
    assert "Validation OK." in result.stdout
