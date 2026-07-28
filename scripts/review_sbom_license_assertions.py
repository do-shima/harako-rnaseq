#!/usr/bin/env python3
"""Classify SPDX NOASSERTION entries using installed, offline image metadata."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import subprocess
import sys
from collections import Counter
from typing import Any
from urllib.parse import unquote


NOASSERTION = {"", "NOASSERTION", "NONE", None}
COPYLEFT_RE = re.compile(r"(?i)\b(?:A?GPL|LGPL|MPL|EUPL|CDDL)[- (]")
CORE_R_PACKAGES = {
    "base",
    "compiler",
    "datasets",
    "grDevices",
    "graphics",
    "grid",
    "methods",
    "parallel",
    "splines",
    "stats",
    "stats4",
    "tcltk",
    "tools",
    "translations",
    "utils",
}
GENERIC_DEBIAN_NAMES = {
    "bash": "bash",
    "curl": "curl",
    "gzip": "gzip",
    "openssl": "openssl",
    "xz": "xz-utils",
}
RPM_DEBIAN_NAMES = {
    "libxau": "libxau6",
}


def _docker_json(image: str, command: list[str]) -> Any:
    completed = subprocess.run(
        ["docker", "run", "--rm", image, *command],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return json.loads(completed.stdout)


def _python_evidence(image: str) -> dict[str, dict[str, str]]:
    code = r"""
import importlib.metadata as m, json, pathlib, re
def classify_license(body):
    low = body.lower()
    if "permission is hereby granted, free of charge" in low:
        return "MIT"
    if "apache license" in low and "version 2.0" in low:
        return "Apache-2.0"
    if "redistribution and use in source and binary forms" in low:
        return "BSD-3-Clause" if "neither the name" in low else "BSD-2-Clause"
    if "gnu general public license" in low:
        return "GPL"
    return ""
rows = {}
for dist in m.distributions():
    md = dist.metadata
    name = re.sub(r"[-_.]+", "-", (md.get("Name") or "").lower())
    classifiers = [
        x.removeprefix("License :: ").strip()
        for x in md.get_all("Classifier", [])
        if x.startswith("License :: ")
    ]
    license_name = (md.get("License-Expression") or "; ".join(classifiers) or md.get("License") or "").strip()
    license_files = [
        str(x) for x in (dist.files or [])
        if "license" in str(x).lower() or "copying" in str(x).lower()
    ]
    if not license_name:
        for item in license_files:
            path = pathlib.Path(dist.locate_file(item))
            if path.is_file():
                license_name = classify_license(path.read_text("utf-8", errors="ignore"))
                if license_name:
                    break
    url = md.get("Home-page") or ""
    if not url:
        for item in md.get_all("Project-URL", []):
            if "," in item:
                url = item.split(",", 1)[1].strip()
                break
    rows[name] = {
        "version": dist.version,
        "license": license_name,
        "source_reference": url,
        "license_files": license_files,
        "vendored": False,
    }
for metadata in pathlib.Path("/usr/local/lib/python3.11/site-packages").rglob("*.dist-info/METADATA"):
    fields = {}
    for line in metadata.read_text("utf-8", errors="ignore").splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields.setdefault(key, []).append(value)
    name = re.sub(r"[-_.]+", "-", fields.get("Name", [""])[0].lower())
    if not name or name in rows:
        continue
    license_files = sorted(
        str(path) for path in metadata.parent.iterdir()
        if "license" in path.name.lower() or "copying" in path.name.lower()
    )
    classifiers = [
        x.removeprefix("License :: ").strip()
        for x in fields.get("Classifier", [])
        if x.startswith("License :: ")
    ]
    license_name = fields.get("License-Expression", [""])[0] or "; ".join(classifiers) or fields.get("License", [""])[0]
    if not license_name:
        for value in license_files:
            license_name = classify_license(pathlib.Path(value).read_text("utf-8", errors="ignore"))
            if license_name:
                break
    rows[name] = {
        "version": fields.get("Version", [""])[0],
        "license": license_name,
        "source_reference": "",
        "license_files": license_files,
        "vendored": "setuptools/_vendor" in str(metadata).replace("\\", "/"),
    }
print(json.dumps(rows, sort_keys=True))
"""
    return _docker_json(image, ["python", "-c", code])


def _r_evidence(image: str) -> dict[str, dict[str, str]]:
    expression = r"""
ip <- installed.packages()
rows <- lapply(seq_len(nrow(ip)), function(i) {
  p <- ip[i, "Package"]
  d <- packageDescription(p)
  list(
    package=p,
    version=ip[i, "Version"],
    license=ifelse(is.null(d$License), "", d$License),
    repository=ifelse(is.null(d$Repository), "", d$Repository),
    url=ifelse(is.null(d$URL), "", paste(d$URL, collapse="; "))
  )
})
cat(jsonlite::toJSON(rows, auto_unbox=TRUE))
"""
    rows = _docker_json(image, ["Rscript", "-e", expression])
    return {row["package"].lower(): row for row in rows}


def _debian_evidence(image: str) -> dict[str, dict[str, Any]]:
    code = r"""
import json, pathlib, re, subprocess
text = subprocess.run(
    ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n"],
    check=True, capture_output=True, text=True
).stdout
rows = {}
for line in text.splitlines():
    name, version = line.split("\t", 1)
    bare = name.split(":", 1)[0]
    candidates = [
        pathlib.Path("/usr/share/doc") / bare / "copyright",
        pathlib.Path("/usr/share/doc") / name / "copyright",
    ]
    copyright_path = next((p for p in candidates if p.is_file()), None)
    body = copyright_path.read_text("utf-8", errors="ignore")[:1000000] if copyright_path else ""
    licenses = sorted(set(re.findall(
        r"(?im)^(?:License|Files-License):\s*([A-Za-z0-9.+-]+)", body
    )))
    rows[bare.lower()] = {
        "version": version,
        "copyright_file": str(copyright_path or ""),
        "license": "; ".join(licenses),
        "source_reference": "https://snapshot.debian.org/",
    }
print(json.dumps(rows, sort_keys=True))
"""
    return _docker_json(image, ["python", "-c", code])


def _npm_evidence(image: str) -> dict[str, dict[str, str]]:
    code = r"""
import json, pathlib
rows = {}
for root in (pathlib.Path("/usr/local/lib/R"), pathlib.Path("/usr/lib/R")):
    if not root.exists():
        continue
    for path in root.rglob("package.json"):
        try:
            item = json.loads(path.read_text("utf-8"))
        except Exception:
            continue
        name = str(item.get("name", "")).lower()
        if name:
            rows[name] = {
                "version": str(item.get("version", "")),
                "license": str(item.get("license") or item.get("licenses") or ""),
                "source_reference": str(item.get("homepage") or item.get("repository") or ""),
                "metadata_file": str(path),
            }
print(json.dumps(rows, sort_keys=True))
"""
    return _docker_json(image, ["python", "-c", code])


def _r_source_evidence(image: str) -> dict[str, dict[str, Any]]:
    code = r"""
import json, pathlib
path = pathlib.Path("/usr/share/licenses/harako-rnaseq/sources/r/SOURCE_MANIFEST.json")
payload = json.loads(path.read_text("utf-8")) if path.is_file() else {"packages": []}
print(json.dumps({
    str(row.get("package", "")).lower(): row
    for row in payload.get("packages", [])
    if row.get("verified") is True
}, sort_keys=True))
"""
    return _docker_json(image, ["python", "-c", code])


def collect_evidence(image: str) -> dict[str, Any]:
    return {
        "python": _python_evidence(image),
        "r": _r_evidence(image),
        "debian": _debian_evidence(image),
        "npm": _npm_evidence(image),
        "r_sources": _r_source_evidence(image),
    }


def _purl(package: dict[str, Any]) -> tuple[str, str, str]:
    refs = package.get("externalRefs") or []
    locator = next(
        (
            item.get("referenceLocator", "")
            for item in refs
            if str(item.get("referenceLocator", "")).startswith("pkg:")
        ),
        "",
    )
    match = re.match(r"pkg:([^/]+)/(?:(?:[^/]+)/)?([^@?]+)", locator)
    if not match:
        return "", "", locator
    return match.group(1).lower(), unquote(match.group(2)), locator


def _license_text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value or "")


def classify_packages(
    document: dict[str, Any], evidence: dict[str, Any]
) -> list[dict[str, Any]]:
    packages = document.get("packages") or []
    declared = {
        (str(item.get("name", "")).lower(), str(item.get("versionInfo", ""))): item.get(
            "licenseDeclared"
        )
        for item in packages
        if item.get("licenseDeclared") not in NOASSERTION
    }
    rows = []
    for package in packages:
        if package.get("licenseDeclared") not in NOASSERTION:
            continue
        name = str(package.get("name", ""))
        version = str(package.get("versionInfo", ""))
        ecosystem, purl_name, locator = _purl(package)
        normalized = re.sub(r"[-_.]+", "-", purl_name.lower())
        category = "genuinely_unresolved"
        license_name = ""
        source = ""
        obligation_addressed: bool | None = None
        detail = ""

        duplicate_license = declared.get((name.lower(), version))
        if (
            ecosystem == "oci"
            or package.get("primaryPackagePurpose") == "OPERATING-SYSTEM"
            or name == "@PKGNAME@"
            or version == "@VERSION@"
        ):
            category = "aggregate_or_virtual"
            detail = "image aggregate or scanner placeholder; no independent payload"
        elif duplicate_license:
            category = "duplicate_representation"
            license_name = str(duplicate_license)
            detail = "same name/version has another SPDX entry with a declared license"
        elif ecosystem == "pypi":
            item = evidence.get("python", {}).get(normalized, {})
            license_name = _license_text(item.get("license"))
            source = str(item.get("source_reference", ""))
            if license_name:
                if item.get("vendored"):
                    category = "duplicate_representation"
                    detail = "vendored payload represented within the setuptools distribution"
                else:
                    category = (
                        "copyleft_source_availability"
                        if COPYLEFT_RE.search(license_name + " ")
                        else "installed_package_metadata"
                    )
                if item.get("license_files"):
                    detail = "; ".join(str(value) for value in item["license_files"])
        elif ecosystem == "cran":
            if name in CORE_R_PACKAGES or name.startswith("testRcpp"):
                category = "duplicate_representation"
                license_name = "R distribution license"
                detail = (
                    "R core package represented by the reviewed R runtime"
                    if name in CORE_R_PACKAGES
                    else "scanner test artifact embedded in an installed R package"
                )
            else:
                item = evidence.get("r", {}).get(name.lower(), {})
                license_name = _license_text(item.get("license"))
                source = str(item.get("url") or item.get("repository") or "")
                if license_name:
                    category = (
                        "copyleft_source_availability"
                        if COPYLEFT_RE.search(license_name + " ")
                        else "installed_package_metadata"
                    )
                    bundled = evidence.get("r_sources", {}).get(name.lower(), {})
                    if (
                        category == "copyleft_source_availability"
                        and str(bundled.get("version") or "") == version
                    ):
                        source = str(bundled.get("source_url") or "")
                        detail = (
                            "exact source archive bundled: "
                            f"{bundled.get('archive')} sha256={bundled.get('sha256')}"
                        )
        elif ecosystem == "deb":
            item = evidence.get("debian", {}).get(name.lower(), {})
            license_name = _license_text(item.get("license"))
            source = str(item.get("source_reference", ""))
            if item.get("copyright_file"):
                category = (
                    "copyleft_source_availability"
                    if COPYLEFT_RE.search(license_name + " ")
                    else "debian_copyright_data"
                )
                detail = str(item.get("copyright_file"))
            elif not item:
                category = "duplicate_representation"
                detail = (
                    "Debian source-package aggregate; installed binary package payload "
                    "is represented separately"
                )
        elif ecosystem == "generic":
            if name.lower() == "python":
                category = "duplicate_representation"
                license_name = "Python Software Foundation License"
                detail = "generic scanner entry duplicates reviewed Python runtime"
            else:
                debian_name = GENERIC_DEBIAN_NAMES.get(name.lower())
                item = evidence.get("debian", {}).get(str(debian_name).lower(), {})
                if item.get("copyright_file"):
                    category = "duplicate_representation"
                    license_name = _license_text(item.get("license"))
                    source = str(item.get("source_reference", ""))
                    detail = f"generic scanner entry duplicates Debian package {debian_name}"
        elif ecosystem == "npm":
            item = evidence.get("npm", {}).get(name.lower(), {})
            license_name = _license_text(item.get("license"))
            source = str(item.get("source_reference", ""))
            if license_name:
                category = "installed_package_metadata"
                detail = str(item.get("metadata_file", ""))
        elif ecosystem == "rpm":
            debian_name = RPM_DEBIAN_NAMES.get(name.lower())
            item = evidence.get("debian", {}).get(str(debian_name).lower(), {})
            if item.get("copyright_file"):
                category = "duplicate_representation"
                license_name = _license_text(item.get("license"))
                source = str(item.get("source_reference", ""))
                detail = (
                    "scanner RPM representation duplicates installed Debian package "
                    f"{debian_name}; evidence: {item.get('copyright_file')}"
                )

        if category == "copyleft_source_availability":
            obligation_addressed = bool(
                name.lower() == "salmon"
                or source
                and (
                    "snapshot.debian.org" in source
                    or "cran" in source.lower()
                    or "bioconductor" in source.lower()
                )
            )
            detail = detail or (
                "version-specific installed metadata recorded; maintainer must confirm "
                "the image distribution method satisfies source-availability terms"
            )
        elif category != "genuinely_unresolved":
            obligation_addressed = True

        rows.append(
            {
                "name": name,
                "version": version,
                "ecosystem": ecosystem,
                "category": category,
                "license": license_name,
                "evidence": detail,
                "source_reference": source,
                "source_obligation_addressed": obligation_addressed,
            }
        )
    return sorted(rows, key=lambda row: (row["category"], row["ecosystem"], row["name"]))


def _write_tsv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sbom", type=pathlib.Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--json-report", type=pathlib.Path, required=True)
    parser.add_argument("--tsv-report", type=pathlib.Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    document = json.loads(args.sbom.read_text("utf-8"))
    evidence = collect_evidence(args.image)
    rows = classify_packages(document, evidence)
    counts = Counter(row["category"] for row in rows)
    unresolved = [row for row in rows if row["category"] == "genuinely_unresolved"]
    unaddressed = [
        row
        for row in rows
        if row["category"] == "copyleft_source_availability"
        and not row["source_obligation_addressed"]
    ]
    payload = {
        "schema_version": 1,
        "scope": "SPDX packages with licenseDeclared NOASSERTION",
        "legal_opinion": False,
        "image": args.image,
        "counts": dict(sorted(counts.items())),
        "unresolved_count": len(unresolved),
        "unaddressed_source_obligation_count": len(unaddressed),
        "release_gate_passed": not unresolved and not unaddressed,
        "entries": rows,
    }
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    _write_tsv(args.tsv_report, rows)
    print(
        f"NOASSERTION={len(rows)} counts={dict(sorted(counts.items()))} "
        f"unresolved={len(unresolved)} unaddressed={len(unaddressed)}"
    )
    return 1 if args.strict and not payload["release_gate_passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
