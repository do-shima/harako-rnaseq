#!/usr/bin/env python3
"""Offline release-readiness checks for source and container metadata."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import jsonschema
import yaml

try:
    from scripts.release_approvals import (
        DEFAULT_EXPECTED_REPOSITORY,
        evaluate_repository_scope,
        validate_history_audit_report,
        validate_maintainer_approvals,
    )
except ModuleNotFoundError:  # Direct execution from scripts/.
    from release_approvals import (
        DEFAULT_EXPECTED_REPOSITORY,
        evaluate_repository_scope,
        validate_history_audit_report,
        validate_maintainer_approvals,
    )


ROOT = pathlib.Path(__file__).resolve().parents[1]
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
LINK_RE = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
PUBLIC_MARKDOWN = (
    ROOT / "README.md",
    ROOT / "README.ja.md",
    ROOT / "SUPPORT.md",
    ROOT / "SECURITY.md",
    ROOT / "COMMERCIAL_LICENSE.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    ROOT / "CONTRIBUTING.md",
    *sorted((ROOT / "docs").rglob("*.md")),
)
IMAGE_FILES = (
    "/usr/share/licenses/harako-rnaseq/LICENSE",
    "/usr/share/licenses/harako-rnaseq/COMMERCIAL_LICENSE.md",
    "/usr/share/licenses/harako-rnaseq/THIRD_PARTY_NOTICES.md",
    "/usr/share/licenses/harako-rnaseq/CITATION.cff",
    "/usr/share/licenses/harako-rnaseq/provenance.md",
    "/usr/share/licenses/harako-rnaseq/third-party/fastp-LICENSE",
    "/usr/share/licenses/harako-rnaseq/third-party/Salmon-GPL-3.0",
    "/usr/share/licenses/harako-rnaseq/third-party/Salmon-SOURCE.md",
    "/usr/share/licenses/harako-rnaseq/sources/r/SOURCE_MANIFEST.json",
    "/usr/share/licenses/harako-rnaseq/sources/r/SOURCE_MANIFEST.tsv",
    "/usr/share/licenses/harako-rnaseq/sources/r/README.txt",
    "/usr/src/salmon-1.10.0.tar.gz",
)


class Checks:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.items.append({"name": name, "passed": bool(passed), "detail": detail})

    @property
    def passed(self) -> bool:
        return all(bool(item["passed"]) for item in self.items)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


def _check_citation(checks: Checks, expected_version: str) -> None:
    citation_path = ROOT / "CITATION.cff"
    schema_path = ROOT / "config" / "cff-schema-1.2.0.json"
    try:
        citation = yaml.safe_load(citation_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(citation, schema)
    except Exception as error:  # validation detail belongs in the report
        checks.add("citation_schema", False, str(error))
        return
    checks.add("citation_schema", True, "CFF 1.2.0 schema")
    checks.add(
        "citation_version",
        citation.get("version") == expected_version,
        f"expected {expected_version}, found {citation.get('version')}",
    )
    checks.add(
        "citation_license",
        citation.get("license") == "PolyForm-Noncommercial-1.0.0",
        str(citation.get("license")),
    )


def _check_tag(checks: Checks, tag: str | None, expected_version: str, strict: bool) -> None:
    if not tag:
        checks.add("tag_format", True, "not requested")
        return
    match = TAG_RE.fullmatch(tag)
    checks.add("tag_format", match is not None, tag)
    if not match:
        return
    checks.add("tag_version", tag[1:] == expected_version, f"{tag} vs {expected_version}")
    is_prerelease = "-beta." in tag
    checks.add(
        "prerelease_latest_policy",
        not (is_prerelease and tag == "latest"),
        "prereleases must not request latest",
    )
    tag_commit = _run(["git", "rev-parse", f"{tag}^{{commit}}"])
    if tag_commit.returncode != 0:
        checks.add("tag_commit", not strict, "tag is not present locally")
        return
    main_ref = next(
        (
            ref
            for ref in ("refs/remotes/origin/main", "refs/heads/main")
            if _run(["git", "show-ref", "--verify", "--quiet", ref]).returncode == 0
        ),
        "",
    )
    if not main_ref:
        checks.add("tag_main_ancestry", not strict, "main ref is unavailable")
        return
    ancestry = _run(["git", "merge-base", "--is-ancestor", tag_commit.stdout.strip(), main_ref])
    checks.add("tag_main_ancestry", ancestry.returncode == 0, main_ref)


def _check_links(checks: Checks) -> None:
    broken: list[str] = []
    for source in PUBLIC_MARKDOWN:
        if not source.is_file():
            broken.append(f"missing {source.relative_to(ROOT)}")
            continue
        for match in LINK_RE.finditer(source.read_text(encoding="utf-8")):
            raw = match.group(1).strip().strip("<>")
            split = urlsplit(raw)
            if not raw or raw.startswith("#") or split.scheme or split.netloc:
                continue
            target = (source.parent / unquote(split.path)).resolve()
            if split.path and not target.exists():
                broken.append(f"{source.relative_to(ROOT)} -> {raw}")
    checks.add("public_links", not broken, "; ".join(broken))


def _check_references(checks: Checks) -> None:
    manifest = yaml.safe_load((ROOT / "workflow" / "ref_manifest.yaml").read_text("utf-8"))
    invalid: list[str] = []
    count = 0
    for preset, releases in manifest.get("presets", {}).items():
        for release, entry in releases.items():
            hashes = entry.get("sha256", {})
            for key in ("transcripts_fasta_url", "genome_fasta_url", "gtf_url"):
                count += 1
                if not HASH_RE.fullmatch(str(hashes.get(key, ""))):
                    invalid.append(f"{preset}/{release}/{key}")
    checks.add("reference_hashes", count == 12 and not invalid, f"{count} hashes; {invalid}")


def _check_repository(checks: Checks) -> None:
    required = ("LICENSE", "CITATION.cff", "THIRD_PARTY_NOTICES.md")
    checks.add("required_metadata", all((ROOT / item).is_file() for item in required))
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
    checks.add(
        "direct_license_inventory",
        "verification required" not in notices.lower(),
        "direct runtime notices must be resolved",
    )
    readme = (ROOT / "README.md").read_text("utf-8")
    readme_ja = (ROOT / "README.ja.md").read_text("utf-8")
    phrase = "PolyForm Noncommercial License 1.0.0"
    checks.add("readme_license_consistency", phrase in readme and phrase in readme_ja)
    tracked = _run(
        [
            "git",
            "ls-files",
            "output",
            "data",
            "data_in",
            "data_out",
            "out_smoke",
            "out_smoke_real",
        ]
    ).stdout.splitlines()
    generated = [item for item in tracked if not item.endswith(".gitkeep")]
    checks.add("generated_data_untracked", not generated, ", ".join(generated))
    combined = "\n".join(path.read_text("utf-8", errors="ignore") for path in PUBLIC_MARKDOWN)
    unsafe = bool(
        re.search(r"[A-Za-z]:\\Users\\[^\\\s]+", combined)
        or re.search(r"<REPLACE_WITH_[^>]+>", combined)
        or re.search(r"(?i)(api[_-]?key|token|password)\s*[:=]\s*['\"][^'\"]+['\"]", combined)
    )
    checks.add("public_text_safety", not unsafe)


def _check_image(checks: Checks, image: str, expected_version: str) -> None:
    inspect = _run(["docker", "image", "inspect", image])
    if inspect.returncode != 0:
        checks.add("image_inspect", False, inspect.stderr.strip())
        return
    metadata = json.loads(inspect.stdout)[0]
    architecture = metadata.get("Architecture")
    checks.add("image_architecture", architecture == "amd64", str(architecture))
    labels = metadata.get("Config", {}).get("Labels", {}) or {}
    expected_revision = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    expected_labels = {
        "org.opencontainers.image.source": "https://github.com/do-shima/harako-rnaseq",
        "org.opencontainers.image.version": expected_version,
        "org.opencontainers.image.revision": expected_revision,
    }
    for key, value in expected_labels.items():
        checks.add(f"image_label:{key}", labels.get(key) == value, str(labels.get(key)))
    created = labels.get("org.opencontainers.image.created", "")
    checks.add("image_label:created", bool(created and created != "unknown"), str(created))
    command = " && ".join(f"test -f {path}" for path in IMAGE_FILES)
    files = _run(["docker", "run", "--rm", image, "bash", "-lc", command])
    checks.add("image_license_files", files.returncode == 0, files.stderr.strip())
    versions = _run(
        [
            "docker",
            "run",
            "--rm",
            image,
            "bash",
            "-lc",
            "python --version && python -m snakemake --version && salmon --version && fastp --version && R --version",
        ]
    )
    checks.add("image_runtime_versions", versions.returncode == 0, versions.stderr.strip())


def _check_phase5b_evidence(
    checks: Checks,
    vulnerability_summary: pathlib.Path | None,
    approval_file: pathlib.Path | None,
    version: str,
    expected_repository: str,
    repository_visibility: str,
) -> None:
    history_path = ROOT / "output/release-audit/git-history-audit.json"
    history_passed, history_errors = validate_history_audit_report(history_path)
    checks.add(
        "history_audit_expected_fixtures",
        history_passed,
        "valid exact fixture registry"
        if history_passed
        else "invalid: " + ", ".join(history_errors),
    )
    source_manifest = yaml.safe_load(
        (ROOT / "config" / "copyleft-r-sources.yaml").read_text("utf-8")
    )
    packages = source_manifest.get("packages") or []
    checks.add(
        "copyleft_source_manifest",
        len(packages) == 10
        and all(HASH_RE.fullmatch(str(item.get("sha256") or "")) for item in packages),
        f"{len(packages)} packages",
    )
    if vulnerability_summary is None or not vulnerability_summary.is_file():
        checks.add("verified_vulnerability_scan", False, "missing Trivy summary")
    else:
        try:
            payload = json.loads(vulnerability_summary.read_text("utf-8"))
            scanned_at = dt.datetime.fromisoformat(
                str(payload.get("scan_timestamp") or "").replace("Z", "+00:00")
            )
            age = dt.datetime.now(dt.timezone.utc) - scanned_at.astimezone(dt.timezone.utc)
            passed = (
                payload.get("status") == "passed"
                and (payload.get("scanner") or {}).get("verified_installation") is True
                and not payload.get("blocking_findings")
                and dt.timedelta(0) <= age <= dt.timedelta(days=7)
            )
            checks.add(
                "verified_vulnerability_scan",
                passed,
                f"age_days={age.total_seconds() / 86400:.2f}",
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            checks.add("verified_vulnerability_scan", False, str(error))
    if repository_visibility == "public":
        checks.add(
            "maintainer_approvals",
            True,
            "not repeated for an already-public repository; exact history and scope remain gated",
        )
    elif approval_file is None:
        checks.add("maintainer_approvals", False, "missing ignored approval file")
    else:
        passed, errors = validate_maintainer_approvals(
            approval_file,
            version,
            root=ROOT,
            require_schema2=True,
        )
        checks.add(
            "maintainer_approvals",
            passed,
            "approved" if passed else "incomplete: " + ", ".join(errors),
        )
    scope = evaluate_repository_scope(ROOT, expected_repository)
    checks.add(
        "public_ref_scope",
        scope.ok,
        f"{scope.mode}: main-only public scope"
        if scope.ok
        else "invalid: " + ", ".join(scope.reason_codes),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--for-image", metavar="IMAGE")
    parser.add_argument("--json-report", type=pathlib.Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--public-beta-candidate", action="store_true")
    parser.add_argument("--vulnerability-summary", type=pathlib.Path)
    parser.add_argument("--approval-file", type=pathlib.Path)
    parser.add_argument(
        "--expected-repository",
        default=DEFAULT_EXPECTED_REPOSITORY,
        help="Expected sanitized GitHub repository URL or canonical identity.",
    )
    parser.add_argument(
        "--repository-visibility",
        choices=("private", "public"),
        default="private",
    )
    args = parser.parse_args()

    checks = Checks()
    _check_repository(checks)
    _check_citation(checks, args.version)
    _check_tag(checks, args.tag, args.version, args.strict)
    _check_links(checks)
    _check_references(checks)
    if args.for_image:
        _check_image(checks, args.for_image, args.version)
    if args.public_beta_candidate:
        _check_phase5b_evidence(
            checks,
            args.vulnerability_summary,
            args.approval_file,
            args.version,
            args.expected_repository,
            args.repository_visibility,
        )

    payload = {"schema_version": 1, "passed": checks.passed, "checks": checks.items}
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for item in checks.items:
        status = "PASS" if item["passed"] else "FAIL"
        detail = f": {item['detail']}" if item["detail"] else ""
        print(f"[{status}] {item['name']}{detail}")
    return 0 if checks.passed or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
