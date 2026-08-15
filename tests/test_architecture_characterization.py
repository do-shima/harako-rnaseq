"""Characterize public contracts before internal architecture changes."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from app.agent_contracts import approval_hash_for, plan_id_for
from app.cli import app
from app.run import RunArgs, build_snakemake_cmd
from app.adapters.snakemake import build_cleanup_metadata_cmd, build_unlock_cmd, snakemake_workdir
from app.ui import run as ui_run
from app.ui import samples_table as ui_samples
from app.ui import scan as ui_scan


RUNNER = CliRunner()
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_root_cli_command_surface_is_stable() -> None:
    result = RUNNER.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("init", "validate", "run", "run-id", "snakemake-version", "fetch", "agent"):
        assert command in result.stdout


def test_agent_cli_command_surface_is_stable() -> None:
    result = RUNNER.invoke(app, ["agent", "--help"])

    assert result.exit_code == 0
    for command in (
        "inspect-input",
        "propose-samples",
        "plan",
        "validate-plan",
        "dry-run",
        "execute",
        "status",
        "artifacts",
        "context",
        "post-analysis-init",
    ):
        assert command in result.stdout


def test_snakemake_command_contract_is_stable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RNASEQ_SNAKEMAKE_WORKDIR_ROOT", str(tmp_path / "work"))
    args = RunArgs(
        input=str(tmp_path / "input"),
        output=str(tmp_path / "output"),
        config=str(tmp_path / "config.yaml"),
        align="none",
        engine="real",
        threads="4",
    )

    command = build_snakemake_cmd(args)

    assert command[1:3] == ["-m", "snakemake"]
    assert command[3] == "--directory"
    assert command[5] == "-s"
    assert Path(command[6]).as_posix().endswith("workflow/Snakefile")
    assert command[7:9] == ["--configfile", str(tmp_path / "config.yaml")]
    assert command[9] == "--config"
    assert command[10:15] == [
        f"input={tmp_path / 'input'}",
        f"output={tmp_path / 'output'}",
        "align=none",
        "engine=real",
        "threads=4",
    ]
    assert command[15:17] == ["--cores", "4"]


def test_ui_recovery_commands_are_constructed_by_the_snakemake_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNASEQ_SNAKEMAKE_WORKDIR_ROOT", str(tmp_path / "work"))
    run_dir = tmp_path / "run"
    config_path = run_dir / "run" / "config_resolved.yaml"
    prefix = [
        "python", "-m", "snakemake", "--directory",
        snakemake_workdir(str(run_dir)), "-s", "workflow/Snakefile",
        "--configfile", str(config_path), "--config", "input=/input", f"output={run_dir}",
    ]

    assert build_cleanup_metadata_cmd(run_dir, config_path, ["a", "b"]) == [
        *prefix, "--cleanup-metadata", "a", "b"
    ]
    assert build_unlock_cmd(run_dir, config_path) == [*prefix, "--unlock"]


def test_fastq_pairing_and_sample_order_are_stable() -> None:
    available = [
        "nested/B_R2.fastq.gz",
        "nested/A_R1.fastq.gz",
        "nested/B_R1.fastq.gz",
        "nested/A_R2.fastq.gz",
    ]
    rows = [
        {"sample": "A", "condition": "Control", "fastq1": "nested/A_R1.fastq.gz", "fastq2": ""},
        {"sample": "B", "condition": "Treatment", "fastq1": "nested/B_R1.fastq.gz", "fastq2": ""},
    ]

    assert ui_scan.read_side("nested/A_R1.fastq.gz") == "1"
    assert ui_scan.sample_base("nested/A_R1.fastq.gz") == "A"
    assert "nested/A_R2.fastq.gz" in ui_scan.infer_pair_candidates("nested/A_R1.fastq.gz")
    assert ui_samples.auto_pair(rows, available) == [
        {"sample": "A", "condition": "Control", "fastq1": "nested/A_R1.fastq.gz", "fastq2": "nested/A_R2.fastq.gz"},
        {"sample": "B", "condition": "Treatment", "fastq1": "nested/B_R1.fastq.gz", "fastq2": "nested/B_R2.fastq.gz"},
    ]


def test_run_identity_and_agent_hash_ignore_only_display_metadata() -> None:
    manifest = ui_run.build_manifest_payload(
        payload={"project_name": "study", "threads": 4, "analysis_plan": {"mode": "qc_only"}},
        rows_raw=[{"sample": "S1", "condition": "A", "fastq1": "S1.fastq.gz", "fastq2": ""}],
        fastq_rel=["S1.fastq.gz"],
        coerce_rows_raw=ui_samples.coerce_rows_raw,
        git_rev="abc123",
        input_root=Path("/input"),
    )
    assert ui_run.manifest_run_id(manifest) == ui_run.manifest_run_id(dict(manifest))

    plan = {
        "schema_version": 1,
        "harako_version": "0.3.0-beta.2",
        "input_root": "/input",
        "output_root": "/output",
        "project_name": "study",
        "samples": [{"sample": "S1", "condition": "A", "fastq1": "S1.fastq.gz", "fastq2": "", "pairing_status": "single-end"}],
        "library_protocol": "full_length",
        "reference": {"canonical_preset": "mouse_ensembl_grcm39"},
        "analysis_plan": {"mode": "qc_only"},
        "contrasts": {"mode": "ref", "reference": "A", "pairs": []},
        "enrichment": {"requested": False, "active": False},
        "resources": {"threads": 4, "execution_engine": "snakemake"},
        "requested_options": {},
    }
    with_display = {**plan, "created_at_utc": "2099-01-01T00:00:00Z", "warnings": ["display only"]}

    assert plan_id_for(plan) == plan_id_for(with_display)
    assert approval_hash_for(plan) == approval_hash_for(with_display)


def test_dependency_boundaries_keep_interfaces_out_of_core() -> None:
    for source_path in sorted((REPOSITORY_ROOT / "app" / "core").glob("*.py")):
        source = source_path.read_text(encoding="utf-8")
        assert "streamlit" not in source
        assert "typer" not in source
        assert "subprocess" not in source
        assert "app.ui" not in source


def test_agent_neutral_module_does_not_depend_on_ui_or_cli() -> None:
    source = (REPOSITORY_ROOT / "app" / "agent.py").read_text(encoding="utf-8")
    assert "app.ui" not in source
    assert "from .ui" not in source
    assert "app.cli" not in source
    assert "from .cli" not in source


def test_streamlit_composition_does_not_construct_subprocesses_or_write_files() -> None:
    source = (REPOSITORY_ROOT / "app" / "ui" / "app_ui.py").read_text(encoding="utf-8")
    assert "subprocess." not in source
    assert "workflow/Snakefile" not in source
    assert ".write_text(" not in source
    assert ".mkdir(" not in source
    assert '.open("w"' not in source
    assert ".open('w'" not in source
