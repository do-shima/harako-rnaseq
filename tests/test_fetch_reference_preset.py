import gzip
import hashlib
import sys
from pathlib import Path

import pytest
import yaml

from scripts import fetch_reference_preset as fetch
from scripts.fetch_reference_preset import (
    DownloadError,
    _ensure_file,
    _remove_invalid_cached_files,
)


def _gzip(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)


def test_existing_verified_file_is_kept(tmp_path):
    source = tmp_path / "source.fa.gz"
    _gzip(source, ">tx\nACGT\n")
    import hashlib

    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    _ensure_file(
        source.as_uri(), [], expected, str(source),
        require_fasta_header=True,
    )
    assert source.exists()


def test_failed_download_cleans_staging_file(tmp_path):
    destination = tmp_path / "target.fa.gz"
    try:
        _ensure_file(
            (tmp_path / "missing.fa.gz").as_uri(),
            [],
            "0" * 64,
            str(destination),
            require_fasta_header=True,
        )
        raise AssertionError("missing source accepted")
    except DownloadError:
        pass
    assert not destination.exists()
    assert not Path(str(destination) + ".download.gz").exists()
    assert not Path(str(destination) + ".download.gz.tmp").exists()


def test_invalid_cached_file_only_is_deleted(tmp_path):
    manifest = {
        "presets": {
            "test": {
                "release-1": {
                    "transcripts_fasta_url": "t",
                    "genome_fasta_url": "g",
                    "gtf_url": "a",
                }
            }
        }
    }
    directory = tmp_path / "test" / "release-1"
    _gzip(directory / "transcripts.fa.gz", ">tx\nACGT\n")
    _gzip(directory / "genome.fa.gz", ">chr\nACGT\n")
    (directory / "annotation.gtf.gz").write_bytes(b"truncated")
    _remove_invalid_cached_files(
        manifest, tmp_path, "test", "release-1",
        {"transcripts_fasta_url": None, "genome_fasta_url": None, "gtf_url": None},
    )
    assert (directory / "transcripts.fa.gz").exists()
    assert (directory / "genome.fa.gz").exists()
    assert not (directory / "annotation.gtf.gz").exists()


def _manifest_and_bundle(tmp_path, *, legacy=False):
    canonical = "test_ensembl"
    release = "release-1"
    directory_name = "old_test" if legacy else canonical
    directory = tmp_path / "cache" / directory_name / release
    _gzip(directory / "transcripts.fa.gz", ">tx testasm\nACGT\n")
    _gzip(directory / "genome.fa.gz", ">chr testasm\nACGT\n")
    _gzip(
        directory / "annotation.gtf.gz",
        '#!genome-build testasm\n'
        'chr\ttest\ttranscript\t1\t4\t.\t+\t.\t'
        'gene_id "g"; transcript_id "t";\n',
    )
    hashes = {
        "transcripts_fasta_url": hashlib.sha256(
            (directory / "transcripts.fa.gz").read_bytes()
        ).hexdigest(),
        "genome_fasta_url": hashlib.sha256(
            (directory / "genome.fa.gz").read_bytes()
        ).hexdigest(),
        "gtf_url": hashlib.sha256(
            (directory / "annotation.gtf.gz").read_bytes()
        ).hexdigest(),
    }
    manifest = {
        "schema_version": 2,
        "aliases": {"old_test": {"canonical_preset": canonical}},
        "preset_metadata": {
            canonical: {
                "provider": "Ensembl",
                "species": "test",
                "assembly": "testasm",
                "annotation_release": "1",
                "display_name": "Test",
                "pinned_release": release,
            }
        },
        "presets": {
            canonical: {
                release: {
                    "transcripts_fasta_url": "https://example.invalid/t.fa.gz",
                    "genome_fasta_url": "https://example.invalid/g.fa.gz",
                    "gtf_url": "https://example.invalid/a.gtf.gz",
                    "sha256": hashes,
                }
            }
        },
    }
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return manifest_path, directory


@pytest.mark.parametrize(
    ("requested", "legacy"),
    [("test_ensembl", False), ("old_test", True)],
)
def test_valid_canonical_or_legacy_cache_uses_no_network(
    monkeypatch, tmp_path, requested, legacy
):
    manifest_path, directory = _manifest_and_bundle(tmp_path, legacy=legacy)
    monkeypatch.setattr(
        fetch,
        "_download_with_fallback",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("network accessed")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_reference_preset.py",
            "--manifest", str(manifest_path),
            "--cache-dir", str(tmp_path / "cache"),
            "--preset", requested,
            "--release", "pinned",
            "--out-json", str(tmp_path / "resolved.json"),
        ],
    )
    assert fetch.main() == 0
    assert directory.exists()


def test_missing_builtin_checksum_is_rejected(monkeypatch, tmp_path):
    manifest_path, _ = _manifest_and_bundle(tmp_path)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["presets"]["test_ensembl"]["release-1"]["sha256"]["gtf_url"] = ""
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_reference_preset.py",
            "--manifest", str(manifest_path),
            "--cache-dir", str(tmp_path / "cache"),
            "--preset", "test_ensembl",
            "--release", "pinned",
        ],
    )
    with pytest.raises(ValueError, match="missing or invalid SHA256"):
        fetch.main()
