#!/usr/bin/env python3
"""Verify the R source bundle and optionally compare it with installed packages."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from typing import Any

from scripts.fetch_copyleft_r_sources import (
    ROOT,
    load_manifest,
    verify_archive,
    write_bundle_metadata,
)


def installed_versions(packages: list[str]) -> dict[str, str]:
    expression = (
        "pkgs <- c("
        + ",".join(json.dumps(package) for package in packages)
        + "); for (p in pkgs) cat(p, as.character(packageDescription(p)$Version), "
        + "sep='\\t', fill=TRUE)"
    )
    result = subprocess.run(
        ["Rscript", "-e", expression],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"Installed R package inspection failed: {result.stderr.strip()}")
    versions: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "\t" in line:
            package, version = line.split("\t", 1)
            versions[package] = version
    return versions


def verify_bundle(
    manifest_path: pathlib.Path,
    bundle_dir: pathlib.Path,
    *,
    check_installed: bool,
) -> dict[str, Any]:
    entries = load_manifest(manifest_path)
    installed = installed_versions([entry["package"] for entry in entries]) if check_installed else {}
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for entry in entries:
        try:
            record = verify_archive(bundle_dir / entry["archive"], entry)
            if check_installed and installed.get(entry["package"]) != entry["version"]:
                raise ValueError(
                    f"{entry['package']}: installed {installed.get(entry['package'])}, "
                    f"source {entry['version']}"
                )
            record["installed_version"] = installed.get(entry["package"], "not_checked")
            records.append(record)
        except ValueError as error:
            errors.append(str(error))
    if errors:
        raise ValueError("; ".join(errors))
    write_bundle_metadata(bundle_dir, records)
    required = ("SOURCE_MANIFEST.json", "SOURCE_MANIFEST.tsv", "README.txt")
    missing = [name for name in required if not (bundle_dir / name).is_file()]
    if missing:
        raise ValueError(f"Source bundle metadata missing: {', '.join(missing)}")
    serialized = "\n".join(path.read_text("utf-8") for path in (bundle_dir / name for name in required))
    if str(ROOT.resolve()) in serialized or str(pathlib.Path.home()) in serialized:
        raise ValueError("Source bundle metadata contains a host-specific path")
    return {
        "schema_version": 1,
        "status": "passed",
        "verified_packages": len(records),
        "check_installed": check_installed,
        "total_archive_size": sum(int(record["size"]) for record in records),
        "unresolved": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=ROOT / "config/copyleft-r-sources.yaml",
    )
    parser.add_argument("--bundle-dir", type=pathlib.Path, required=True)
    parser.add_argument("--check-installed", action="store_true")
    parser.add_argument("--json-report", type=pathlib.Path)
    args = parser.parse_args()
    payload = verify_bundle(
        args.manifest.resolve(),
        args.bundle_dir.resolve(),
        check_installed=args.check_installed,
    )
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
