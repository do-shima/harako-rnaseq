from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts import fetch_copyleft_r_sources as sources
from scripts import verify_copyleft_r_sources as verifier
from tests.git_helpers import tracked_paths


ROOT = Path(__file__).resolve().parents[1]


def make_archive(path: Path, package: str, version: str, license_value: str = "GPL") -> str:
    payload = (
        f"Package: {package}\nVersion: {version}\nLicense: {license_value}\nRepository: CRAN\n"
    ).encode()
    with tarfile.open(path, "w:gz") as bundle:
        info = tarfile.TarInfo(f"{package}/DESCRIPTION")
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(package: str, version: str, archive: Path, digest: str) -> dict[str, str]:
    return {
        "package": package,
        "version": version,
        "ecosystem": "CRAN",
        "source_url": f"https://cran.r-project.org/src/contrib/{archive.name}",
        "project_url": f"https://cran.r-project.org/package={package}",
        "archive": archive.name,
        "sha256": digest,
        "license_evidence": "DESCRIPTION License: GPL",
    }


def test_exact_source_archive_is_verified(tmp_path):
    archive = tmp_path / "example_1.0.tar.gz"
    digest = make_archive(archive, "example", "1.0")
    record = sources.verify_archive(archive, entry("example", "1.0", archive, digest))
    assert record["verified"] is True
    assert record["description_license"] == "GPL"


def test_wrong_source_version_sha_and_missing_description_are_rejected(tmp_path):
    archive = tmp_path / "example_1.0.tar.gz"
    digest = make_archive(archive, "example", "2.0")
    with pytest.raises(ValueError, match="DESCRIPTION"):
        sources.verify_archive(archive, entry("example", "1.0", archive, digest))
    with pytest.raises(ValueError, match="SHA256"):
        sources.verify_archive(archive, entry("example", "2.0", archive, "0" * 64))
    missing = tmp_path / "missing.tar.gz"
    with tarfile.open(missing, "w:gz"):
        pass
    with pytest.raises(ValueError, match="DESCRIPTION"):
        sources.parse_description(missing, "example")


def test_atomic_download_cleanup(monkeypatch, tmp_path):
    destination = tmp_path / "source.tar.gz"

    def fail(*_args, **_kwargs):
        raise OSError("interrupted")

    monkeypatch.setattr(sources.urllib.request, "urlopen", fail)
    with pytest.raises(OSError, match="interrupted"):
        sources._download_atomic(
            "https://cran.r-project.org/src/contrib/example_1.0.tar.gz", destination
        )
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".tmp").exists()


def test_manifest_has_exact_ten_packages_and_official_ecosystems():
    entries = sources.load_manifest(ROOT / "config/copyleft-r-sources.yaml")
    assert {entry["package"] for entry in entries} == {
        "bbmle",
        "codetools",
        "emdbook",
        "formatR",
        "highr",
        "knitr",
        "mime",
        "qvalue",
        "snow",
        "tximport",
    }
    by_name = {entry["package"]: entry for entry in entries}
    assert "Archive/highr" in by_name["highr"]["source_url"]
    assert "/3.21/bioc/" in by_name["qvalue"]["source_url"]
    assert "/3.21/bioc/" in by_name["tximport"]["source_url"]
    assert by_name["codetools"]["ecosystem"] == "CRAN recommended"


def test_source_bundle_metadata_is_deterministic(tmp_path):
    records = [
        {
            **entry("zeta", "1", tmp_path / "zeta_1.tar.gz", "a" * 64),
            "size": 2,
        },
        {
            **entry("alpha", "1", tmp_path / "alpha_1.tar.gz", "b" * 64),
            "size": 1,
        },
    ]
    sources.write_bundle_metadata(tmp_path, records)
    first = (tmp_path / "SOURCE_MANIFEST.json").read_bytes()
    sources.write_bundle_metadata(tmp_path, list(reversed(records)))
    assert (tmp_path / "SOURCE_MANIFEST.json").read_bytes() == first
    payload = json.loads(first)
    assert [item["package"] for item in payload["packages"]] == ["alpha", "zeta"]


def test_installed_version_mismatch_is_rejected(monkeypatch, tmp_path):
    archive = tmp_path / "example_1.0.tar.gz"
    digest = make_archive(archive, "example", "1.0")
    monkeypatch.setattr(verifier, "load_manifest", lambda _path: [entry("example", "1.0", archive, digest)])
    monkeypatch.setattr(verifier, "installed_versions", lambda _packages: {"example": "2.0"})
    with pytest.raises(ValueError, match="installed 2.0"):
        verifier.verify_bundle(tmp_path / "manifest.yaml", tmp_path, check_installed=True)


def test_source_archives_are_not_tracked():
    tracked = tracked_paths(ROOT, "*.tar.gz", "output/release-audit")
    assert not [path for path in tracked if path != "output/.gitkeep"]
