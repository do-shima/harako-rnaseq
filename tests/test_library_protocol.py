from pathlib import Path

import pytest
import yaml

from app import cli
from app.analysis_eligibility import analysis_plan_from_rows
from app.library_protocol import (
    LEGACY_UNSPECIFIED,
    is_frozen_run_config,
    resolve_library_protocol,
)


@pytest.mark.parametrize("protocol", ["full_length", "three_prime_tag"])
def test_new_library_protocols_are_explicit_and_normalized(protocol):
    assert resolve_library_protocol(protocol) == protocol


@pytest.mark.parametrize(
    "inferred_value",
    ["sample_3prime.fastq.gz", "SRR123", "75bp", "NovaSeq", "QuantSeq"],
)
def test_library_protocol_is_never_inferred(inferred_value):
    with pytest.raises(ValueError, match="Invalid library_protocol"):
        resolve_library_protocol(inferred_value)


def test_missing_protocol_is_allowed_only_for_old_frozen_run(tmp_path):
    frozen = tmp_path / "run" / "config_resolved.yaml"
    frozen.parent.mkdir()
    frozen.write_text("engine: real\n", encoding="utf-8")
    assert is_frozen_run_config(frozen)
    assert resolve_library_protocol(None, legacy_frozen=True) == LEGACY_UNSPECIFIED
    with pytest.raises(ValueError, match="required for new runs"):
        resolve_library_protocol(None)


def test_old_frozen_config_resolves_legacy_without_rewrite(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sample_table = run_dir / "samples.tsv"
    sample_table.write_text(
        (
            "sample\tcondition\tfastq1\n"
            "A1\tA\ta1.fastq\nA2\tA\ta2.fastq\n"
            "B1\tB\tb1.fastq\nB2\tB\tb2.fastq\n"
        ),
        encoding="utf-8",
    )
    frozen = run_dir / "config_resolved.yaml"
    frozen.write_text(
        yaml.safe_dump({"sample_table": str(sample_table), "engine": "real"}),
        encoding="utf-8",
    )
    before = frozen.read_bytes()
    resolved = cli._resolve_run_cfg(
        yaml.safe_load(frozen.read_text(encoding="utf-8")),
        str(frozen),
        str(tmp_path),
        str(tmp_path / "out"),
        "none",
        "real",
        "1",
        False,
    )
    assert resolved["library_protocol"] == LEGACY_UNSPECIFIED
    assert frozen.read_bytes() == before


def test_protocol_participates_in_existing_run_identity(tmp_path):
    sample_table = tmp_path / "samples.tsv"
    sample_table.write_text(
        "sample\tcondition\tfastq1\nA1\tA\ta.fastq\n",
        encoding="utf-8",
    )
    base = {
        "engine": "stub",
        "library_protocol": "full_length",
        "input": str(tmp_path),
        "output": str(tmp_path / "out"),
        "sample_table": str(sample_table),
        "analysis_plan": analysis_plan_from_rows([{"sample": "A1", "condition": "A"}]),
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(base), encoding="utf-8")
    first = cli._resolve_run_cfg(base, str(config_path), str(tmp_path), str(tmp_path / "out"), "none", "stub", "1", False)
    changed = dict(base, library_protocol="three_prime_tag")
    second = cli._resolve_run_cfg(changed, str(config_path), str(tmp_path), str(tmp_path / "out"), "none", "stub", "1", False)
    assert cli._manifest_run_id(cli._build_manifest_payload(str(config_path), first)) != cli._manifest_run_id(
        cli._build_manifest_payload(str(config_path), second)
    )
