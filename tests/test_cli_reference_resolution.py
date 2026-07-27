from pathlib import Path

from app.cli import (
    _build_manifest_payload,
    _manifest_run_id,
    _resolve_reference_cfg,
)


MANIFEST = Path(__file__).resolve().parents[1] / "workflow" / "ref_manifest.yaml"


def test_legacy_cli_config_migrates_to_canonical_release(tmp_path):
    cfg = {
        "species": "mouse",
        "output": str(tmp_path),
        "ref_manifest": str(MANIFEST),
        "ref_cache_dir": str(tmp_path / "refs_cache"),
        "ref_preset": "mouse_gencode_mm10",
        "ref_release": "release-113",
    }
    resolved = _resolve_reference_cfg(cfg, str(tmp_path / "config.yaml"))
    assert resolved["ref_preset"] == "mouse_ensembl_grcm38"
    assert resolved["ref_release"] == "release-102"
    assert resolved["reference_provenance"]["requested_preset"] == "mouse_gencode_mm10"
    assert resolved["reference_provenance"]["manifest_release"] == "release-102"
    assert "release-102" in resolved["ref"]["mouse"]["gtf"]


def test_frozen_direct_reference_paths_are_not_rewritten(tmp_path):
    direct = {
        "transcripts_fasta": "/frozen/transcripts.fa.gz",
        "genome_fasta": "/frozen/genome.fa.gz",
        "gtf": "/frozen/annotation.gtf.gz",
    }
    cfg = {
        "species": "mouse",
        "ref_preset": "mouse_gencode",
        "ref_release": "release-113",
        "ref": {"mouse": direct},
    }
    assert _resolve_reference_cfg(cfg, str(tmp_path / "config.yaml")) == cfg


def test_alias_migration_alone_does_not_change_run_id(tmp_path):
    base = {
        "species": "mouse",
        "output": str(tmp_path),
        "ref_manifest": str(MANIFEST),
        "ref_cache_dir": str(tmp_path / "refs_cache"),
        "ref_release": "release-113",
    }
    alias_cfg = _resolve_reference_cfg(
        {**base, "ref_preset": "mouse_gencode"},
        str(tmp_path / "config.yaml"),
    )
    canonical_cfg = _resolve_reference_cfg(
        {**base, "ref_preset": "mouse_ensembl_grcm39"},
        str(tmp_path / "config.yaml"),
    )
    alias_payload = _build_manifest_payload("missing.yaml", alias_cfg)
    canonical_payload = _build_manifest_payload("missing.yaml", canonical_cfg)
    assert _manifest_run_id(alias_payload) == _manifest_run_id(canonical_payload)
