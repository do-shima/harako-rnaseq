#!/usr/bin/env python3
"""Fetch and verify exact R source archives listed in a pinned manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import tarfile
import urllib.parse
import urllib.request
from typing import Any

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_INITIAL_HOSTS = {"cran.r-project.org", "bioconductor.org"}
ALLOWED_REDIRECT_HOSTS = {
    "cran.r-project.org",
    "bioconductor.org",
    "archive.bioconductor.org",
    "mghp.osn.xsede.org",
}


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_description(archive: pathlib.Path, package: str) -> dict[str, str]:
    with tarfile.open(archive, "r:gz") as bundle:
        name = f"{package}/DESCRIPTION"
        members = [member for member in bundle.getmembers() if member.name == name and member.isfile()]
        if len(members) != 1:
            raise ValueError(f"{archive.name}: expected one {name}")
        stream = bundle.extractfile(members[0])
        if stream is None:
            raise ValueError(f"{archive.name}: DESCRIPTION is unreadable")
        text = stream.read().decode("utf-8", "replace")
    fields: dict[str, str] = {}
    current = ""
    for line in text.splitlines():
        if line[:1].isspace() and current:
            fields[current] += " " + line.strip()
        elif ":" in line:
            current, value = line.split(":", 1)
            fields[current] = value.strip()
    return fields


def validate_entry(entry: dict[str, Any]) -> dict[str, str]:
    required = (
        "package",
        "version",
        "ecosystem",
        "source_url",
        "project_url",
        "archive",
        "sha256",
        "license_evidence",
    )
    missing = [key for key in required if not str(entry.get(key) or "").strip()]
    if missing:
        raise ValueError(f"Source entry is missing: {', '.join(missing)}")
    result = {key: str(entry[key]) for key in required}
    if not HASH_RE.fullmatch(result["sha256"]):
        raise ValueError(f"{result['package']}: invalid SHA256")
    url = urllib.parse.urlsplit(result["source_url"])
    if url.scheme != "https" or url.hostname not in ALLOWED_INITIAL_HOSTS:
        raise ValueError(f"{result['package']}: source URL is not an approved official host")
    if pathlib.PurePath(result["archive"]).name != result["archive"]:
        raise ValueError(f"{result['package']}: archive name must be a filename")
    return result


def load_manifest(path: pathlib.Path) -> list[dict[str, str]]:
    payload = yaml.safe_load(path.read_text("utf-8")) or {}
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported copyleft source manifest schema")
    entries = [validate_entry(entry) for entry in payload.get("packages") or []]
    names = [entry["package"] for entry in entries]
    if len(entries) != 10 or len(set(names)) != len(names):
        raise ValueError("Copyleft source manifest must contain ten unique packages")
    return sorted(entries, key=lambda item: item["package"].lower())


def _download_atomic(url: str, destination: pathlib.Path) -> str:
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "Harako-RNAseq-source-bundle"}
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as output:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname not in ALLOWED_REDIRECT_HOSTS:
                raise ValueError(f"Unexpected R source redirect host: {final.hostname}")
            shutil.copyfileobj(response, output)
            final_url = response.geturl()
        if temporary.stat().st_size == 0:
            raise ValueError("Downloaded source archive is empty")
        os.replace(temporary, destination)
        return final_url
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def verify_archive(path: pathlib.Path, entry: dict[str, str]) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"{entry['package']}: source archive is missing or empty")
    digest = sha256_file(path)
    if digest != entry["sha256"]:
        raise ValueError(f"{entry['package']}: source archive SHA256 mismatch")
    fields = parse_description(path, entry["package"])
    if fields.get("Package") != entry["package"] or fields.get("Version") != entry["version"]:
        raise ValueError(
            f"{entry['package']}: DESCRIPTION is {fields.get('Package')} {fields.get('Version')}, "
            f"expected {entry['package']} {entry['version']}"
        )
    return {
        **entry,
        "size": path.stat().st_size,
        "description_license": fields.get("License", ""),
        "description_repository": fields.get("Repository", ""),
        "description_priority": fields.get("Priority", ""),
        "verified": True,
    }


def write_bundle_metadata(output_dir: pathlib.Path, records: list[dict[str, Any]]) -> None:
    ordered = sorted(records, key=lambda item: item["package"].lower())
    payload = {
        "schema_version": 1,
        "statement": "Engineering source-availability evidence; not legal advice.",
        "packages": ordered,
    }
    (output_dir / "SOURCE_MANIFEST.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    columns = (
        "package",
        "version",
        "ecosystem",
        "archive",
        "sha256",
        "size",
        "source_url",
        "project_url",
        "license_evidence",
    )
    lines = ["\t".join(columns)]
    lines.extend("\t".join(str(record[column]) for column in columns) for record in ordered)
    (output_dir / "SOURCE_MANIFEST.tsv").write_text("\n".join(lines) + "\n", "utf-8")
    (output_dir / "README.txt").write_text(
        "Harako-RNAseq corresponding R source bundle\n"
        "\n"
        "These archives correspond to the listed installed R packages. Exact versions\n"
        "and SHA256 values are recorded in SOURCE_MANIFEST.json and .tsv. Harako-RNAseq\n"
        "does not modify these packages unless separately documented. Each archive\n"
        "retains its upstream license and is included as source-availability evidence.\n"
        "This engineering record is not legal advice.\n",
        "utf-8",
    )


def fetch_sources(
    manifest_path: pathlib.Path,
    output_dir: pathlib.Path,
    *,
    no_network: bool = False,
) -> list[dict[str, Any]]:
    entries = load_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for entry in entries:
        destination = output_dir / entry["archive"]
        if destination.is_file():
            try:
                record = verify_archive(destination, entry)
                record["cache_source"] = "existing"
                records.append(record)
                continue
            except ValueError:
                destination.unlink(missing_ok=True)
        if no_network:
            raise ValueError(f"{entry['package']}: verified archive is unavailable offline")
        final_url = _download_atomic(entry["source_url"], destination)
        record = verify_archive(destination, entry)
        record["cache_source"] = "downloaded"
        record["final_host"] = urllib.parse.urlsplit(final_url).hostname
        records.append(record)
    write_bundle_metadata(output_dir, records)
    return sorted(records, key=lambda item: item["package"].lower())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=ROOT / "config/copyleft-r-sources.yaml",
    )
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--no-network", action="store_true")
    args = parser.parse_args()
    records = fetch_sources(args.manifest.resolve(), args.output_dir.resolve(), no_network=args.no_network)
    print(f"verified R source archives: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
