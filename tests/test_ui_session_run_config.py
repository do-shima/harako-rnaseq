import json
from pathlib import Path

import pytest
import yaml

from app.ui import run as ui_run
from app.ui import state as ui_state


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_samples(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("sample\tcondition\tfastq1\ns1\tA\ts1_R1.fastq.gz\n", encoding="utf-8")


def test_session_state_defaults_are_centralized_idempotent_and_isolated():
    first = {"rows": [{"sample": "S1"}], "run_status": "completed"}
    second = {}

    ui_state.initialize_session_state(first, {"paired": True}, coerce_rows=lambda rows: list(rows))
    ui_state.initialize_session_state(first, {"paired": False}, coerce_rows=lambda rows: list(rows))
    ui_state.initialize_session_state(second, {"paired": False}, coerce_rows=lambda rows: list(rows))

    assert first["rows_raw"] == [{"sample": "S1"}]
    assert first["run_status"] == "completed"
    assert first["paired"] is True
    assert second["paired"] is False
    first["op_logs"]["save"] = "changed"
    assert second["op_logs"]["save"] == ""


def test_session_scoped_paths_keep_ui_state_independent(tmp_path):
    output_root = tmp_path / "output"
    session_a = "a" * 32
    session_b = "b" * 32

    state_a = ui_state.session_ui_state_path(output_root, session_a)
    state_b = ui_state.session_ui_state_path(output_root, session_b)
    config_a = ui_state.session_config_path(output_root, session_a)
    config_b = ui_state.session_config_path(output_root, session_b)
    samples_a = ui_state.session_samples_path(output_root, session_a)
    samples_b = ui_state.session_samples_path(output_root, session_b)

    _write_json(state_a, {"project_name": "SessionA"})
    _write_json(state_b, {"project_name": "SessionB"})
    _write_yaml(config_a, {"project_name": "ConfigA"})
    _write_yaml(config_b, {"project_name": "ConfigB"})
    _write_samples(samples_a)
    _write_samples(samples_b)

    assert state_a != state_b
    assert config_a != config_b
    assert samples_a != samples_b
    assert json.loads(state_a.read_text(encoding="utf-8"))["project_name"] == "SessionA"
    assert json.loads(state_b.read_text(encoding="utf-8"))["project_name"] == "SessionB"
    assert yaml.safe_load(config_a.read_text(encoding="utf-8"))["project_name"] == "ConfigA"
    assert yaml.safe_load(config_b.read_text(encoding="utf-8"))["project_name"] == "ConfigB"


def test_resume_uses_run_local_config_even_if_session_and_global_differ(tmp_path):
    output_root = tmp_path / "output"
    run_dir = output_root / "data_out" / "demo_run"
    session_samples = ui_state.session_samples_path(output_root, "a" * 32)
    session_cfg = ui_state.session_config_path(output_root, "a" * 32)
    legacy_cfg = output_root / "config.yaml"

    _write_samples(session_samples)
    _write_yaml(session_cfg, {"project_name": "session_cfg"})
    _write_yaml(legacy_cfg, {"project_name": "legacy_cfg"})

    run_cfg_path = ui_run.write_frozen_run_config(
        run_dir,
        {"project_name": "frozen_run", "threads": 3, "sample_table": str(session_cfg)},
        sample_table_source=session_samples,
    )

    resolved = ui_run.resolve_run_config_path(run_dir)
    cmd = ui_run.build_snakemake_base_cmd(run_dir, resolved, 3)

    assert resolved == run_cfg_path
    assert resolved != session_cfg
    assert resolved != legacy_cfg
    assert cmd[cmd.index("--configfile") + 1] == str(run_cfg_path)


def test_frozen_config_preserves_reference_provenance_and_direct_paths(tmp_path):
    run_dir = tmp_path / "output" / "data_out" / "demo_run"
    direct = {
        "transcripts_fasta": "/output/refs_cache/mouse_gencode/release-113/transcripts.fa.gz",
        "genome_fasta": "/output/refs_cache/mouse_gencode/release-113/genome.fa.gz",
        "gtf": "/output/refs_cache/mouse_gencode/release-113/annotation.gtf.gz",
    }
    provenance = {
        "canonical_preset": "mouse_ensembl_grcm39",
        "provider": "Ensembl",
        "assembly": "GRCm39",
        "annotation_release": "113",
        "manifest_release": "release-113",
        "checksum_verified": True,
        "cache_source": "legacy_alias",
        "checksums": {
            "transcripts_fasta": "a" * 64,
            "genome_fasta": "b" * 64,
            "gtf": "c" * 64,
        },
        **direct,
    }
    path = ui_run.write_frozen_run_config(
        run_dir,
        {
            "species": "mouse",
            "ref_preset": "mouse_ensembl_grcm39",
            "ref": {"mouse": direct},
            "reference_provenance": provenance,
        },
    )
    frozen = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert frozen["ref"]["mouse"] == direct
    assert frozen["reference_provenance"] == provenance


def test_recover_unlock_fails_cleanly_when_run_local_config_missing(tmp_path):
    run_dir = tmp_path / "output" / "data_out" / "demo_run"
    run_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(FileNotFoundError, match="config_resolved.yaml"):
        ui_run.resolve_run_config_path(run_dir)


def test_legacy_global_config_does_not_affect_run_record(tmp_path):
    output_root = tmp_path / "output"
    run_dir = output_root / "data_out" / "demo_run"
    session_samples = ui_state.session_samples_path(output_root, "b" * 32)

    _write_yaml(output_root / "config.yaml", {"project_name": "legacy_global", "threads": 99})
    _write_samples(session_samples)
    run_cfg_path = ui_run.write_frozen_run_config(
        run_dir,
        {"project_name": "frozen_run", "threads": 2},
        sample_table_source=session_samples,
    )
    _write_json(run_dir / "run" / "manifest.json", {"run_id": "demo", "payload": {"config": {"project_name": "frozen_run"}}})
    _write_json(run_dir / "run" / "metadata.json", {"run_id": "demo", "threads": 2})

    record = ui_run.load_run_record(run_dir)

    assert record["config_path"] == run_cfg_path
    assert record["config"]["project_name"] == "frozen_run"
    assert record["config"]["threads"] == 2
    assert record["metadata"]["run_id"] == "demo"


def test_run_local_config_resolution_tolerates_windows_style_slashes(tmp_path):
    output_root = tmp_path / "output"
    run_dir = output_root / "data_out" / "demo_run"
    session_samples = ui_state.session_samples_path(output_root, "c" * 32)

    _write_samples(session_samples)
    run_cfg_path = ui_run.write_frozen_run_config(run_dir, {"project_name": "demo"}, sample_table_source=session_samples)

    windows_style_run_dir = Path(str(run_dir).replace("/", "\\"))
    resolved = ui_run.resolve_run_config_path(windows_style_run_dir)

    assert resolved == run_cfg_path


def test_session_path_generation_is_stable_across_reruns(tmp_path):
    output_root = tmp_path / "output"
    session_id = "d" * 32

    first = {
        "root": ui_state.session_root(output_root, session_id),
        "state": ui_state.session_ui_state_path(output_root, session_id),
        "config": ui_state.session_config_path(output_root, session_id),
        "samples": ui_state.session_samples_path(output_root, session_id),
    }
    second = {
        "root": ui_state.session_root(output_root, session_id),
        "state": ui_state.session_ui_state_path(output_root, session_id),
        "config": ui_state.session_config_path(output_root, session_id),
        "samples": ui_state.session_samples_path(output_root, session_id),
    }

    assert first == second
    assert first["root"].as_posix().endswith(f"ui_sessions/{session_id}")
