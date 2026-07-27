import gzip
import json
import shutil
from pathlib import Path

import yaml
import pytest

from scripts import pin_reference_checksums as pin
from scripts.pin_reference_checksums import (
    inspect_bundle,
    preflight_presets,
    validate_reference_file,
)


def _write_gzip(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)


def _fixture_manifest():
    return {
        "schema_version": 2,
        "preset_metadata": {
            "test_ensembl": {
                "provider": "Ensembl",
                "species": "test",
                "assembly": "test",
                "annotation_release": "1",
                "display_name": "Test",
                "pinned_release": "release-1",
            }
        },
        "presets": {
            "test_ensembl": {
                "release-1": {
                    "transcripts_fasta_url": "https://example.invalid/test.cdna.fa.gz",
                    "genome_fasta_url": "https://example.invalid/test.dna.fa.gz",
                    "gtf_url": "https://example.invalid/test.1.gtf.gz",
                    "sha256": {},
                }
            }
        },
    }


def test_dry_inspection_validates_and_hashes(tmp_path):
    bundle = tmp_path / "test_ensembl" / "release-1"
    _write_gzip(bundle / "transcripts.fa.gz", ">tx test\nACGT\n")
    _write_gzip(bundle / "genome.fa.gz", ">chr1 test\nACGT\n")
    _write_gzip(
        bundle / "annotation.gtf.gz",
        '#!genome-build test\n'
        'chr1\ttest\ttranscript\t1\t4\t.\t+\t.\tgene_id "g"; transcript_id "t";\n',
    )
    report = inspect_bundle(
        _fixture_manifest(), tmp_path, "test_ensembl", "pinned", download_missing=False
    )
    assert report["status"] == "valid"
    assert all(len(value) == 64 and value == value.lower() for value in report["sha256"].values())


def test_invalid_gzip_fasta_and_gtf(tmp_path):
    broken = tmp_path / "broken.fa.gz"
    broken.write_bytes(b"not gzip")
    try:
        validate_reference_file(broken, "fasta")
        raise AssertionError("invalid gzip accepted")
    except ValueError as exc:
        assert "gzip" in str(exc)
    fasta = tmp_path / "bad.fa.gz"
    _write_gzip(fasta, "ACGT\n")
    try:
        validate_reference_file(fasta, "fasta")
        raise AssertionError("invalid FASTA accepted")
    except ValueError as exc:
        assert "FASTA" in str(exc)
    gtf = tmp_path / "bad.gtf.gz"
    _write_gzip(gtf, "chr1\ttoo\tfew\n")
    try:
        validate_reference_file(gtf, "gtf_url")
        raise AssertionError("invalid GTF accepted")
    except ValueError as exc:
        assert "GTF" in str(exc)


def _mock_remote(url):
    return {
        "url": url,
        "final_url": url,
        "http_status": 200,
        "method": "HEAD",
        "content_length": 100,
        "filename": Path(url).name,
    }


def test_preflight_reports_content_length_and_space(monkeypatch, tmp_path):
    monkeypatch.setattr(pin, "_request_preflight", _mock_remote)
    monkeypatch.setattr(
        pin.shutil,
        "disk_usage",
        lambda _: shutil._ntuple_diskusage(total=10_000, used=0, free=10_000),
    )
    report = preflight_presets(
        _fixture_manifest(), tmp_path, ["test_ensembl"], "pinned"
    )
    assert len(report["assets"]) == 3
    assert report["disk"]["final_missing_bytes"] == 300
    assert report["disk"]["largest_temporary_bytes"] == 100
    assert report["disk"]["required_bytes"] == 480
    assert report["disk"]["sufficient"] is True


def test_insufficient_disk_stops_preflight(monkeypatch, tmp_path):
    monkeypatch.setattr(pin, "_request_preflight", _mock_remote)
    monkeypatch.setattr(
        pin.shutil,
        "disk_usage",
        lambda _: shutil._ntuple_diskusage(total=100, used=0, free=100),
    )
    with pytest.raises(ValueError, match="insufficient disk"):
        preflight_presets(
            _fixture_manifest(), tmp_path, ["test_ensembl"], "pinned"
        )


def _write_bundle(cache: Path):
    bundle = cache / "test_ensembl" / "release-1"
    _write_gzip(bundle / "transcripts.fa.gz", ">tx test\nACGT\n")
    _write_gzip(bundle / "genome.fa.gz", ">chr1 test\nACGT\n")
    _write_gzip(
        bundle / "annotation.gtf.gz",
        '#!genome-build test\n'
        'chr1\ttest\ttranscript\t1\t4\t.\t+\t.\tgene_id "g"; transcript_id "t";\n',
    )


def test_dry_run_without_download_has_no_network(monkeypatch, tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(_fixture_manifest(), sort_keys=False), encoding="utf-8"
    )
    _write_bundle(tmp_path / "cache")
    monkeypatch.setattr(
        pin, "_request_preflight",
        lambda _: (_ for _ in ()).throw(AssertionError("network accessed")),
    )
    assert pin.main(
        [
            "--manifest", str(manifest_path),
            "--cache-dir", str(tmp_path / "cache"),
            "--preset", "test_ensembl",
            "--release", "pinned",
            "--dry-run",
        ]
    ) == 0


def test_download_missing_dry_run_keeps_manifest_unchanged(
    monkeypatch, tmp_path
):
    manifest_path = tmp_path / "manifest.yaml"
    before = yaml.safe_dump(_fixture_manifest(), sort_keys=False)
    manifest_path.write_text(before, encoding="utf-8")
    monkeypatch.setattr(pin, "_request_preflight", _mock_remote)

    def fake_download(url, destination):
        staged = destination.with_name(destination.name + ".tmp.gz")
        if destination.name == "annotation.gtf.gz":
            _write_gzip(
                staged,
                '#!genome-build test\n'
                'chr1\ttest\ttranscript\t1\t4\t.\t+\t.\t'
                'gene_id "g"; transcript_id "t";\n',
            )
        else:
            _write_gzip(staged, ">seq test\nACGT\n")
        return staged

    monkeypatch.setattr(pin, "_download_atomic", fake_download)
    report_path = tmp_path / "report.json"
    assert pin.main(
        [
            "--manifest", str(manifest_path),
            "--cache-dir", str(tmp_path / "cache"),
            "--preset", "test_ensembl",
            "--release", "pinned",
            "--download-missing",
            "--dry-run",
            "--output-report", str(report_path),
        ]
    ) == 0
    assert manifest_path.read_text(encoding="utf-8") == before
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["results"][0]["status"] == "valid"


def test_write_is_network_free_atomic_and_hashing_stable(
    monkeypatch, tmp_path
):
    manifest_path = tmp_path / "manifest.yaml"
    manifest = _fixture_manifest()
    manifest["aliases"] = {"old_test": {"canonical_preset": "test_ensembl"}}
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    cache = tmp_path / "cache"
    _write_bundle(cache)
    first = inspect_bundle(
        manifest, cache, "test_ensembl", "pinned", download_missing=False
    )
    second = inspect_bundle(
        manifest, cache, "test_ensembl", "pinned", download_missing=False
    )
    assert first["sha256"] == second["sha256"]
    assert all(
        len(value) == 64 and value == value.lower()
        for value in first["sha256"].values()
    )
    monkeypatch.setattr(
        pin, "_request_preflight",
        lambda _: (_ for _ in ()).throw(AssertionError("network accessed")),
    )
    assert pin.main(
        [
            "--manifest", str(manifest_path),
            "--cache-dir", str(cache),
            "--preset", "test_ensembl",
            "--release", "pinned",
            "--write",
        ]
    ) == 0
    written = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert written["aliases"] == manifest["aliases"]
    assert written["presets"]["test_ensembl"]["release-1"]["sha256"] == first["sha256"]
    assert not list(tmp_path.glob("*.tmp"))
