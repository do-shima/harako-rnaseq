import json
from pathlib import Path

from app.ui import run as ui_run


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def test_log_resolver_prefers_metadata_recorded_paths(tmp_path):
    run_dir = tmp_path / "output" / "data_out" / "demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata_main = tmp_path / "workdir" / ".snakemake" / "log" / "real.snakemake.log"
    metadata_main.parent.mkdir(parents=True, exist_ok=True)
    metadata_main.write_text("real log", encoding="utf-8")
    naive_log = run_dir / ".snakemake" / "log" / "naive.snakemake.log"
    naive_log.parent.mkdir(parents=True, exist_ok=True)
    naive_log.write_text("naive log", encoding="utf-8")
    stderr_log = run_dir / "run" / "snakemake_stderr.txt"
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    stderr_log.write_text("stderr", encoding="utf-8")
    _write_json(
        run_dir / "run" / "metadata.json",
        {
            "runtime_logs": {
                "main_log": str(metadata_main),
                "stderr": str(stderr_log),
                "workdir": str(tmp_path / "workdir"),
            }
        },
    )

    info = ui_run.snakemake_log_candidates(run_dir)

    assert info["primary"]["path"] == metadata_main
    assert info["candidates"][0]["path"] == metadata_main


def test_open_existing_unavailable_without_report():
    modes = ui_run.available_run_modes(run_exists=True, has_frozen_run=True, has_report=False)
    assert "open_existing" not in modes
    assert modes == ["resume"]


def test_public_error_formatter_strips_traceback_and_absolute_paths(tmp_path):
    run_dir = tmp_path / "output" / "data_out" / "demo"
    raw = "\n".join(
        [
            "Traceback (most recent call last):",
            f'  File "{tmp_path / "host" / "app_ui.py"}", line 12, in <module>',
            f"Missing run-local config: {run_dir / 'run' / 'config_resolved.yaml'}",
            "RuntimeError: boom",
        ]
    )

    public = ui_run.format_public_error(raw, run_dir=run_dir, output_root=tmp_path / "output")

    assert "Traceback" not in public
    assert str(tmp_path) not in public
    assert "run/run/config_resolved.yaml" in public or "config_resolved.yaml" in public


def test_public_path_formatter_normalizes_windows_style_paths(tmp_path):
    output_root = tmp_path / "output"
    run_dir = output_root / "data_out" / "demo"
    run_cfg = run_dir / "run" / "config_resolved.yaml"
    run_cfg.parent.mkdir(parents=True, exist_ok=True)
    run_cfg.write_text("project_name: demo\n", encoding="utf-8")

    formatted = ui_run.format_public_path(
        Path(str(run_cfg).replace("/", "\\")),
        run_dir=Path(str(run_dir).replace("/", "\\")),
        output_root=Path(str(output_root).replace("/", "\\")),
    )

    assert formatted == "run/run/config_resolved.yaml"


def test_build_dev_summary_reports_run_local_config_and_validation(tmp_path):
    output_root = tmp_path / "output"
    run_dir = output_root / "data_out" / "demo"
    samples = output_root / "ui_sessions" / ("a" * 32) / "metadata" / "samples.tsv"
    samples.parent.mkdir(parents=True, exist_ok=True)
    samples.write_text("sample\tcondition\tfastq1\ns1\tA\ts1_R1.fastq.gz\n", encoding="utf-8")
    run_cfg = ui_run.write_frozen_run_config(run_dir, {"project_name": "demo"}, sample_table_source=samples)
    session_cfg = output_root / "ui_sessions" / ("a" * 32) / "config.yaml"

    summary = ui_run.build_dev_summary(
        ui_session_id="a" * 32,
        run_id="demo",
        session_config_path=session_cfg,
        run_dir=run_dir,
        validation_state={"ok": False, "detail": "validation pending", "ts": "2026-03-30T00:00:00+00:00"},
    )

    assert summary["ui_session_id"] == "a" * 32
    assert summary["run_id"] == "demo"
    assert summary["session_config_path"] == str(session_cfg)
    assert summary["run_local_config_path"] == str(run_cfg)
    assert summary["validation"]["ok"] is False
    assert summary["validation"]["detail"] == "validation pending"
