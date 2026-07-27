from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
import yaml

from app.reference_presets import (
    ReferencePresetError,
    get_legacy_aliases_for_preset,
    get_preset_releases,
    iter_cache_candidates,
    resolve_existing_cache_paths,
    resolve_preset_id,
    resolve_preset_release,
    build_custom_reference_provenance,
    build_reference_provenance,
    validate_builtin_manifest,
)


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "workflow" / "ref_manifest.yaml"


def manifest():
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_canonical_and_all_legacy_aliases():
    data = manifest()
    expected = {
        "human_gencode": "human_ensembl_grch38",
        "mouse_gencode": "mouse_ensembl_grcm39",
        "mouse_gencode_mm10": "mouse_ensembl_grcm38",
        "rat_ensembl": "rat_ensembl_mratbn7_2",
    }
    for alias, canonical in expected.items():
        assert resolve_preset_id(data, alias) == canonical
        assert alias in get_legacy_aliases_for_preset(data, canonical)
        assert resolve_preset_id(data, canonical) == canonical


def test_grcm38_historical_release_is_explicitly_mapped():
    assert resolve_preset_release(
        manifest(), "mouse_gencode_mm10", "release-113"
    ) == ("mouse_ensembl_grcm38", "release-102")


def test_unknown_and_alias_cycle_fail():
    with pytest.raises(ReferencePresetError, match="Unknown"):
        resolve_preset_id(manifest(), "unknown")
    cyclic = {"presets": {}, "aliases": {"a": "b", "b": "a"}}
    with pytest.raises(ReferencePresetError, match="cycle"):
        resolve_preset_id(cyclic, "a")


def test_legacy_schema_loading():
    old = {
        "presets": {
            "old": {
                "pinned": {"transcripts_fasta_url": "t", "genome_fasta_url": "g", "gtf_url": "a"},
                "release-1": {"transcripts_fasta_url": "t", "genome_fasta_url": "g", "gtf_url": "a"},
            }
        }
    }
    assert resolve_preset_release(old, "old", "pinned") == ("old", "pinned")
    assert get_preset_releases(old, "old") == ["pinned", "release-1"]


def _touch_bundle(directory: Path):
    directory.mkdir(parents=True)
    for filename in ("transcripts.fa.gz", "genome.fa.gz", "annotation.gtf.gz"):
        (directory / filename).write_bytes(b"x")


def test_cache_precedence_and_no_copy(tmp_path):
    data = manifest()
    data["presets"]["mouse_ensembl_grcm39"]["release-113"]["sha256"] = {}
    legacy = tmp_path / "mouse_gencode" / "release-113"
    _touch_bundle(legacy)
    first = resolve_existing_cache_paths(
        data, tmp_path, "mouse_gencode", "release-113"
    )
    assert first["directory"] == legacy
    assert first["cache_source"] == "legacy_alias"
    canonical = tmp_path / "mouse_ensembl_grcm39" / "release-113"
    _touch_bundle(canonical)
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    second = resolve_existing_cache_paths(
        data, tmp_path, "mouse_gencode", "release-113"
    )
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert second["directory"] == canonical
    assert before == after


def test_grcm38_old_release_cache_rejected_without_pinned_hashes(tmp_path):
    old_release = tmp_path / "mouse_gencode_mm10" / "release-113"
    _touch_bundle(old_release)
    assert resolve_existing_cache_paths(
        manifest(), tmp_path, "mouse_gencode_mm10", "release-113"
    ) is None


def test_grcm38_old_release_cache_is_accepted_only_after_hash_match(tmp_path):
    data = manifest()
    old_release = tmp_path / "mouse_gencode_mm10" / "release-113"
    _touch_bundle(old_release)
    import hashlib

    digest = hashlib.sha256(b"x").hexdigest()
    data["presets"]["mouse_ensembl_grcm38"]["release-102"]["sha256"] = {
        key: digest
        for key in ("transcripts_fasta_url", "genome_fasta_url", "gtf_url")
    }
    result = resolve_existing_cache_paths(
        data, tmp_path, "mouse_gencode_mm10", "release-113"
    )
    assert result["directory"] == old_release
    assert result["verified"] is True


def test_windows_and_unix_candidate_paths():
    data = manifest()
    win = list(iter_cache_candidates(
        data, PureWindowsPath("C:/refs"), "mouse_gencode", "release-113"
    ))
    unix = list(iter_cache_candidates(
        data, PurePosixPath("/refs"), "mouse_gencode", "release-113"
    ))
    assert str(win[0]["directory"]).endswith(
        r"mouse_ensembl_grcm39\release-113"
    )
    assert str(unix[0]["directory"]) == "/refs/mouse_ensembl_grcm39/release-113"


def test_custom_references_are_unaffected(tmp_path):
    custom = tmp_path / "custom.fa"
    custom.write_text(">tx\nACGT\n", encoding="utf-8")
    paths = {"transcripts_fasta": str(custom)}
    provenance = build_custom_reference_provenance("mouse", paths)
    assert provenance["provider"] == "custom"
    assert provenance["checksum_verified"] is False
    assert provenance["transcripts_fasta"] == str(custom)
    assert len(provenance["checksums"]["transcripts_fasta"]) == 64
    assert provenance["local_checksums_calculated"] is True


def test_verified_provenance_contains_exact_manifest_hashes():
    data = manifest()
    provenance = build_reference_provenance(
        data,
        "mouse_gencode",
        "release-113",
        checksum_verified=True,
        cache_source="legacy_alias",
    )
    expected = data["presets"]["mouse_ensembl_grcm39"]["release-113"]["sha256"]
    assert provenance["checksums"] == {
        "transcripts_fasta": expected["transcripts_fasta_url"],
        "genome_fasta": expected["genome_fasta_url"],
        "gtf": expected["gtf_url"],
    }
    assert provenance["checksum_verified"] is True


def test_schema_v2_missing_checksum_is_manifest_error():
    data = manifest()
    data["presets"]["human_ensembl_grch38"]["release-113"]["sha256"]["gtf_url"] = ""
    with pytest.raises(ReferencePresetError, match="missing or invalid SHA256"):
        validate_builtin_manifest(data)
