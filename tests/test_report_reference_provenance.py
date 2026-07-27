from pathlib import Path


def test_report_renders_reference_metadata_without_reference_paths():
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "report_real.Rmd"
    ).read_text(encoding="utf-8")
    for field in (
        "provider",
        "species",
        "assembly",
        "annotation_release",
        "manifest_release",
        "canonical_preset",
        "checksum_verified",
    ):
        assert f"provenance${field}" in source
    reference_section = source.split("# Reference provenance", 1)[1].split(
        "# Contrasts", 1
    )[0]
    assert "provenance$transcripts_fasta" not in reference_section
    assert "provenance$genome_fasta" not in reference_section
    assert "provenance$gtf" not in reference_section
    assert "abbreviated_hashes" in reference_section
    assert "Full reference checksums" in reference_section


def test_stub_report_renders_metadata_without_reference_paths():
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "report_stub.py"
    ).read_text(encoding="utf-8")
    for field in (
        "provider",
        "species",
        "assembly",
        "annotation_release",
        "manifest_release",
        "canonical_preset",
        "checksum_verified",
    ):
        assert f'provenance.get("{field}"' in source
    assert 'provenance.get("transcripts_fasta"' not in source
    assert 'provenance.get("genome_fasta"' not in source
    assert 'provenance.get("gtf"' not in source
    assert "Full reference checksums" in source
    assert "verification_status" in source
