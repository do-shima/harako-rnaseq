#!/usr/bin/env python3
"""Install a checksum-verified Trivy release into the ignored output tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_VERSION = "0.70.0"
COMPROMISED_VERSIONS = {"0.69.4", "0.69.5", "0.69.6"}
RELEASES = {
    "0.70.0": {
        "commit": "8a3177aedf7ee0864920eb1852eef031cd3742b8",
        "checksums_sha256": "c45281240bb9211ea9e830fc0bf5cf8acf7c0ca830feb64ac8a0aa932c5c92d9",
    }
}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
ALLOWED_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com"}


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_version(version: str) -> str:
    normalized = version.removeprefix("v")
    if normalized.lower() == "latest" or not VERSION_RE.fullmatch(normalized):
        raise ValueError("Trivy version must be an immutable numeric release")
    if normalized in COMPROMISED_VERSIONS:
        raise ValueError(f"Trivy {normalized} is rejected due to the 2026 supply-chain incident")
    if normalized not in RELEASES:
        raise ValueError(f"Trivy {normalized} has not been explicitly reviewed")
    return normalized


def select_asset(version: str, system: str | None = None, machine: str | None = None) -> tuple[str, str]:
    system_name = (system or platform.system()).lower()
    machine_name = (machine or platform.machine()).lower()
    if machine_name not in {"amd64", "x86_64"}:
        raise ValueError(f"Unsupported Trivy architecture: {machine_name}")
    if system_name == "windows":
        return f"trivy_{version}_windows-64bit.zip", "trivy.exe"
    if system_name == "linux":
        return f"trivy_{version}_Linux-64bit.tar.gz", "trivy"
    raise ValueError(f"Unsupported Trivy platform: {system_name}")


def release_url(version: str, filename: str) -> str:
    if version.lower() == "latest" or "latest" in filename.lower():
        raise ValueError("Mutable Trivy release URLs are not permitted")
    return f"https://github.com/aquasecurity/trivy/releases/download/v{version}/{filename}"


def _download_atomic(url: str, destination: pathlib.Path) -> str:
    requested = urllib.parse.urlsplit(url)
    if requested.scheme != "https" or requested.hostname != "github.com":
        raise ValueError("Trivy downloads must start at the official GitHub release URL")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "Harako-RNAseq-release-audit"}
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as output:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname not in ALLOWED_DOWNLOAD_HOSTS:
                raise ValueError(f"Unexpected Trivy download redirect host: {final.hostname}")
            shutil.copyfileobj(response, output)
        if temporary.stat().st_size == 0:
            raise ValueError("Downloaded Trivy artifact is empty")
        os.replace(temporary, destination)
        return response.geturl()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _checksum_for(checksums: pathlib.Path, asset_name: str) -> str:
    for line in checksums.read_text("utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset_name:
            digest = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    raise ValueError(f"No valid checksum found for {asset_name}")


def _safe_extract(archive: pathlib.Path, destination: pathlib.Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = (destination / member.filename).resolve()
                if destination.resolve() not in target.parents and target != destination.resolve():
                    raise ValueError(f"Unsafe archive member: {member.filename}")
            bundle.extractall(destination)
        return
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise ValueError(f"Unsafe archive member: {member.name}")
        bundle.extractall(destination)


def install(
    version: str,
    install_root: pathlib.Path,
    report_path: pathlib.Path,
    *,
    system: str | None = None,
    machine: str | None = None,
) -> dict[str, object]:
    version = validate_version(version)
    release = RELEASES[version]
    asset_name, executable_name = select_asset(version, system, machine)
    install_dir = install_root / version
    install_dir.mkdir(parents=True, exist_ok=True)
    checksums_name = f"trivy_{version}_checksums.txt"
    checksums_path = install_dir / checksums_name
    archive_path = install_dir / asset_name

    checksums_url = release_url(version, checksums_name)
    archive_url = release_url(version, asset_name)
    checksums_final_url = _download_atomic(checksums_url, checksums_path)
    checksums_digest = sha256_file(checksums_path)
    if checksums_digest != release["checksums_sha256"]:
        checksums_path.unlink(missing_ok=True)
        raise ValueError("Official Trivy checksum manifest hash does not match reviewed metadata")

    archive_final_url = _download_atomic(archive_url, archive_path)
    expected_archive_digest = _checksum_for(checksums_path, asset_name)
    archive_digest = sha256_file(archive_path)
    if archive_digest != expected_archive_digest:
        archive_path.unlink(missing_ok=True)
        raise ValueError("Trivy archive checksum mismatch")

    with tempfile.TemporaryDirectory(dir=install_dir) as temporary:
        extracted = pathlib.Path(temporary)
        _safe_extract(archive_path, extracted)
        candidates = [path for path in extracted.rglob(executable_name) if path.is_file()]
        if len(candidates) != 1:
            raise ValueError(f"Expected one {executable_name} in Trivy archive")
        executable = install_dir / executable_name
        shutil.copy2(candidates[0], executable)
        if executable_name != "trivy.exe":
            executable.chmod(0o755)

    result = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or f"Version: {version}" not in result.stdout:
        executable.unlink(missing_ok=True)
        raise ValueError(f"Installed Trivy version check failed: {result.stderr.strip()}")

    payload: dict[str, object] = {
        "schema_version": 1,
        "verified": True,
        "version": version,
        "release_commit": release["commit"],
        "asset": asset_name,
        "archive_sha256": archive_digest,
        "checksums_sha256": checksums_digest,
        "binary_sha256": sha256_file(executable),
        "binary": executable.relative_to(ROOT).as_posix(),
        "install_directory": install_dir.relative_to(ROOT).as_posix(),
        "archive_url": archive_url,
        "archive_final_host": urllib.parse.urlsplit(archive_final_url).hostname,
        "checksums_url": checksums_url,
        "checksums_final_host": urllib.parse.urlsplit(checksums_final_url).hostname,
        "system_install": False,
        "sigstore_verified": False,
        "sigstore_note": "Checksum manifest digest is pinned; Sigstore verification was not required.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--install-root", type=pathlib.Path, default=ROOT / "output/tools/trivy")
    parser.add_argument(
        "--report",
        type=pathlib.Path,
        default=ROOT / "output/release-audit/trivy-installation.json",
    )
    args = parser.parse_args()
    payload = install(args.version, args.install_root.resolve(), args.report.resolve())
    print(
        f"verified Trivy {payload['version']} "
        f"archive_sha256={payload['archive_sha256']} binary_sha256={payload['binary_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
