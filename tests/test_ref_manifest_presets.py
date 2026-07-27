from pathlib import Path

import yaml

from app.reference_presets import (
    get_preset_metadata,
    get_preset_releases,
    get_release_entry,
    resolve_preset_release,
    validate_builtin_manifest,
)


EXPECTED = {
    "human_ensembl_grch38": ("human", "GRCh38", "113", "release-113"),
    "mouse_ensembl_grcm39": ("mouse", "GRCm39", "113", "release-113"),
    "mouse_ensembl_grcm38": ("mouse", "GRCm38", "102", "release-102"),
    "rat_ensembl_mratbn7_2": ("rat", "mRatBN7.2", "113", "release-113"),
}


def _load_manifest():
    path = Path(__file__).resolve().parents[1] / "workflow" / "ref_manifest.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main():
    manifest = _load_manifest()
    assert manifest["schema_version"] == 2
    validate_builtin_manifest(manifest)
    assert set(manifest["presets"]) == set(EXPECTED)
    for preset, (species, assembly, annotation, release) in EXPECTED.items():
        metadata = get_preset_metadata(manifest, preset)
        assert metadata["provider"] == "Ensembl"
        assert metadata["species"] == species
        assert metadata["assembly"] == assembly
        assert metadata["annotation_release"] == annotation
        assert resolve_preset_release(manifest, preset, "pinned") == (preset, release)
        assert get_preset_releases(manifest, preset) == ["pinned", release]
        _, _, block = get_release_entry(manifest, preset, release)
        assert ".ensembl.org/pub/release-" in block["gtf_url"]
        assert "GENCODE" not in metadata["display_name"].upper()
    rat = manifest["presets"]["rat_ensembl_mratbn7_2"]["release-113"]
    assert rat["genome_fasta_url"].endswith(".dna.toplevel.fa.gz")
    grcm38 = manifest["presets"]["mouse_ensembl_grcm38"]["release-102"]
    assert ".GRCm38.102.gtf.gz" in grcm38["gtf_url"]
    for preset, (_, _, _, release) in EXPECTED.items():
        hashes = manifest["presets"][preset][release]["sha256"]
        assert set(hashes) == {
            "transcripts_fasta_url", "genome_fasta_url", "gtf_url"
        }
        assert all(len(value) == 64 and value == value.lower() for value in hashes.values())
    structural = {"schema_version", "aliases", "preset_metadata"}
    assert not structural.intersection(get_preset_releases(manifest, "mouse_ensembl_grcm39"))


def test_reference_manifest_presets():
    main()


if __name__ == "__main__":
    main()
