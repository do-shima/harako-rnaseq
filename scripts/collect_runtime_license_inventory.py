#!/usr/bin/env python3
"""Collect deterministic, offline license metadata for direct image dependencies."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import pathlib
import shutil
import subprocess
import sys
from typing import Any


PYTHON_PACKAGES = {
    "snakemake": "Snakemake",
    "streamlit": "Streamlit",
    "pandas": "pandas",
    "PyYAML": "PyYAML",
    "typer": "Typer",
}
PYTHON_LICENSES = {
    "snakemake": "MIT",
    "streamlit": "Apache-2.0",
    "pandas": "BSD-3-Clause",
    "PyYAML": "MIT",
    "typer": "MIT",
}
R_PACKAGES = (
    "data.table",
    "readr",
    "dplyr",
    "ggplot2",
    "rmarkdown",
    "jsonlite",
    "yaml",
    "BiocManager",
    "tximport",
    "DESeq2",
    "apeglm",
    "EnhancedVolcano",
    "clusterProfiler",
    "fgsea",
    "AnnotationDbi",
    "GO.db",
    "org.Hs.eg.db",
    "org.Mm.eg.db",
    "org.Rn.eg.db",
)


def _record(
    name: str,
    version: str,
    ecosystem: str,
    license_name: str,
    source: str,
    *,
    license_file: str = "",
    project_url: str = "",
    direct: bool = True,
) -> dict[str, Any]:
    unresolved = not all((version, license_name, source))
    return {
        "component": name,
        "version": version,
        "ecosystem": ecosystem,
        "license": license_name,
        "license_file": license_file,
        "project_url": project_url,
        "verification_source": source,
        "direct_dependency": direct,
        "unresolved": unresolved,
    }


def _python_records() -> list[dict[str, Any]]:
    rows = []
    for distribution, display_name in PYTHON_PACKAGES.items():
        try:
            dist = importlib.metadata.distribution(distribution)
        except importlib.metadata.PackageNotFoundError:
            rows.append(_record(display_name, "", "python", "", ""))
            continue
        metadata = dist.metadata
        license_name = (metadata.get("License-Expression") or metadata.get("License") or "").strip()
        license_name = PYTHON_LICENSES.get(distribution, license_name)
        if not license_name:
            classifiers = [
                item.removeprefix("License :: ").strip()
                for item in metadata.get_all("Classifier", [])
                if item.startswith("License :: ")
            ]
            license_name = "; ".join(classifiers)
        license_files = sorted(
            str(path)
            for path in (dist.files or ())
            if "license" in str(path).lower() or "copying" in str(path).lower()
        )
        project_url = metadata.get("Home-page", "")
        if not project_url:
            for value in metadata.get_all("Project-URL", []):
                if "," in value:
                    project_url = value.split(",", 1)[1].strip()
                    break
        rows.append(
            _record(
                display_name,
                dist.version,
                "python",
                license_name,
                "installed Python distribution metadata",
                license_file="; ".join(license_files),
                project_url=project_url,
            )
        )
    return rows


def _r_records() -> list[dict[str, Any]]:
    if not shutil.which("Rscript"):
        return [_record(name, "", "R", "", "") for name in R_PACKAGES]
    package_vector = ",".join(json.dumps(name) for name in R_PACKAGES)
    expression = (
        f"pkgs <- c({package_vector}); "
        "for (p in pkgs) { "
        "if (!requireNamespace(p, quietly=TRUE)) { "
        "cat(p, '\\t\\t\\t\\t\\n', sep=''); next }; "
        "d <- packageDescription(p); "
        "lf <- c(system.file('LICENSE', package=p), system.file('LICENCE', package=p)); "
        "lf <- lf[nzchar(lf)]; "
        "cat(p, d$Version, d$License, paste(lf, collapse='; '), d$URL %||% '', sep='\\t'); cat('\\n') }"
    )
    expression = expression.replace(
        "d$URL %||% ''", "ifelse(is.null(d$URL), '', paste(d$URL, collapse='; '))"
    )
    completed = subprocess.run(
        ["Rscript", "-e", expression],
        check=True,
        capture_output=True,
        text=True,
    )
    by_name: dict[str, list[str]] = {}
    for line in completed.stdout.splitlines():
        parts = line.split("\t")
        if parts:
            by_name[parts[0]] = parts
    rows = []
    for name in R_PACKAGES:
        parts = by_name.get(name, [name, "", "", "", ""])
        version = parts[1] if len(parts) > 1 else ""
        license_name = parts[2] if len(parts) > 2 else ""
        license_file = parts[3] if len(parts) > 3 else ""
        url = parts[4] if len(parts) > 4 else ""
        rows.append(
            _record(
                name,
                version,
                "R",
                license_name,
                "installed R package DESCRIPTION",
                license_file=license_file,
                project_url=url,
            )
        )
    return rows


def collect_inventory() -> list[dict[str, Any]]:
    os_release = pathlib.Path("/etc/os-release")
    debian_version = ""
    if os_release.is_file():
        values = dict(
            line.split("=", 1)
            for line in os_release.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
        debian_version = values.get("VERSION_ID", "").strip('"')
    rows = [
        _record(
            "Debian and apt runtime packages",
            debian_version,
            "operating-system",
            "component-specific Debian licenses",
            "installed dpkg metadata and /usr/share/doc/*/copyright",
            project_url="https://www.debian.org/",
        ),
        _record(
            "Python",
            sys.version.split()[0],
            "runtime",
            "Python Software Foundation License",
            "installed runtime license",
            license_file="/usr/local/lib/python3.11/LICENSE.txt",
            project_url="https://www.python.org/",
        ),
        _record(
            "R",
            _command_version(["R", "--version"]),
            "runtime",
            "GPL-2.0-or-later",
            "installed runtime and COPYING",
            project_url="https://www.r-project.org/",
        ),
        _record(
            "fastp",
            _command_version(["fastp", "--version"]),
            "binary",
            "MIT",
            "bundled exact upstream license notice",
            license_file="/usr/share/licenses/harako-rnaseq/third-party/fastp-LICENSE",
            project_url="https://github.com/OpenGene/fastp",
        ),
        _record(
            "Salmon",
            _command_version(["salmon", "--version"]),
            "binary",
            "GPL-3.0",
            "bundled GPL text and corresponding source archive",
            license_file="/usr/share/licenses/harako-rnaseq/third-party/Salmon-GPL-3.0",
            project_url="https://github.com/COMBINE-lab/salmon",
        ),
    ]
    rows.extend(_python_records())
    rows.extend(_r_records())
    return sorted(rows, key=lambda item: (item["ecosystem"].lower(), item["component"].lower()))


def _command_version(command: list[str]) -> str:
    if not shutil.which(command[0]):
        return ""
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    text = (completed.stdout or completed.stderr).strip().splitlines()
    return text[0] if text else ""


def _write_tsv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", type=pathlib.Path)
    parser.add_argument("--tsv-output", type=pathlib.Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    rows = collect_inventory()
    payload = {
        "schema_version": 1,
        "scope": "direct bundled and runtime dependencies",
        "legal_opinion": False,
        "components": rows,
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.tsv_output:
        _write_tsv(args.tsv_output, rows)
    if not args.json_output and not args.tsv_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    unresolved = [row["component"] for row in rows if row["unresolved"]]
    if unresolved:
        print("Unresolved direct components: " + ", ".join(unresolved), file=sys.stderr)
    return 1 if args.strict and unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
