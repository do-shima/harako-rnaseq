#!/usr/bin/env python3
"""Offline, non-mutating gate for a Harako-RNAseq public-beta candidate."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Any

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_FILES = (
    "CHANGELOG.md",
    "LICENSE",
    "CITATION.cff",
    "THIRD_PARTY_NOTICES.md",
    "docs/releases/v0.2.0-beta.1.md",
    "docs/public-beta-launch-runbook.md",
    "docs/transitive-license-review.md",
    "docs/vulnerability-review-v0.2.0-beta.1.md",
    "docs/beta-feedback.md",
    ".github/ISSUE_TEMPLATE/beta_feedback.yml",
)


def _run(root: pathlib.Path, command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)


def _check(name: str, passed: bool, detail: str = "", status: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status or ("pass" if passed else "fail"),
        "passed": bool(passed),
        "detail": detail,
    }


def check_version_consistency(
    root: pathlib.Path, version: str, expected_tag: str, image: str | None = None
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    citation = yaml.safe_load((root / "CITATION.cff").read_text("utf-8"))
    checks.append(
        _check("citation_version", citation.get("version") == version, str(citation.get("version")))
    )
    namespace: dict[str, str] = {}
    exec((root / "app" / "version.py").read_text("utf-8"), namespace)
    checks.append(_check("application_version", namespace.get("VERSION") == version, namespace.get("VERSION", "")))
    checks.append(_check("expected_tag", expected_tag == f"v{version}", expected_tag))
    release_text = (root / "docs" / "releases" / f"v{version}.md").read_text("utf-8")
    checks.append(_check("release_notes_version", version in release_text, version))
    workflow = (root / ".github" / "workflows" / "publish-image.yml").read_text("utf-8")
    checks.append(_check("publish_workflow_version", f"v{version}" in workflow, f"v{version}"))
    checks.append(
        _check(
            "prerelease_latest_policy",
            "-beta." not in version
            or "type=raw,value=latest,enable=${{ !contains" in workflow,
            "beta must not publish latest",
        )
    )
    if image:
        inspect = _run(root, ["docker", "image", "inspect", image])
        if inspect.returncode:
            checks.append(_check("image_version", False, inspect.stderr.strip()))
        else:
            metadata = json.loads(inspect.stdout)[0]
            image_version = (metadata.get("Config", {}).get("Labels", {}) or {}).get(
                "org.opencontainers.image.version", ""
            )
            checks.append(_check("image_version", image_version == version, str(image_version)))
    return checks


def tag_check(
    root: pathlib.Path, expected_tag: str, allow_missing: bool, require_annotated: bool = False
) -> dict[str, Any]:
    result = _run(root, ["git", "rev-parse", "--verify", f"{expected_tag}^{{commit}}"])
    if result.returncode == 0:
        if require_annotated:
            tag_type = _run(root, ["git", "cat-file", "-t", expected_tag])
            if tag_type.returncode or tag_type.stdout.strip() != "tag":
                return _check("release_tag", False, f"{expected_tag} is not annotated")
            main_ref = "refs/heads/main"
            ancestry = _run(
                root,
                ["git", "merge-base", "--is-ancestor", f"{expected_tag}^{{commit}}", main_ref],
            )
            if ancestry.returncode:
                return _check("release_tag", False, f"{expected_tag} is not reachable from main")
        return _check("release_tag", True, expected_tag)
    if allow_missing:
        return _check(
            "release_tag",
            True,
            f"{expected_tag} is an expected manual gate",
            status="manual_gate",
        )
    return _check("release_tag", False, f"{expected_tag} is absent")


def _report_check(
    name: str,
    path: pathlib.Path,
    *,
    allowed_statuses: set[str],
) -> dict[str, Any]:
    if not path.is_file():
        return _check(name, False, f"missing ignored report: {path}")
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return _check(name, False, str(error))
    status = str(payload.get("status") or "")
    if name == "license_review":
        passed = bool(payload.get("release_gate_passed"))
        detail = (
            f"unresolved={payload.get('unresolved_count')} "
            f"unaddressed={payload.get('unaddressed_source_obligation_count')}"
        )
        return _check(name, passed, detail)
    return _check(name, status in allowed_statuses, status)


def _parse_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def check_vulnerability_evidence(
    root: pathlib.Path,
    image: str,
    path: pathlib.Path,
    *,
    now: dt.datetime | None = None,
    max_age_days: int = 7,
) -> dict[str, Any]:
    if not path.is_file():
        return _check("verified_vulnerability_scan", False, "missing Trivy summary")
    try:
        payload = json.loads(path.read_text("utf-8"))
        scanned_at = _parse_timestamp(str(payload.get("scan_timestamp") or ""))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return _check("verified_vulnerability_scan", False, f"invalid summary: {error}")
    inspect = _run(root, ["docker", "image", "inspect", image])
    if inspect.returncode:
        return _check("verified_vulnerability_scan", False, "candidate image is unavailable")
    image_id = json.loads(inspect.stdout)[0].get("Id")
    scanned_image_id = (payload.get("image") or {}).get("id")
    current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    age = current - scanned_at
    counts = payload.get("counts") or {}
    blockers = payload.get("blocking_findings") or []
    passed = (
        payload.get("status") == "passed"
        and (payload.get("scanner") or {}).get("verified_installation") is True
        and image_id == scanned_image_id
        and dt.timedelta(0) <= age <= dt.timedelta(days=max_age_days)
        and not blockers
        and bool(payload.get("all_highs_dispositioned", True))
    )
    detail = (
        f"image_match={image_id == scanned_image_id}; age_days={age.total_seconds() / 86400:.2f}; "
        f"critical={counts.get('CRITICAL', 0)}; high={counts.get('HIGH', 0)}; "
        f"blockers={len(blockers)}"
    )
    return _check("verified_vulnerability_scan", passed, detail)


APPROVAL_FIELDS = (
    ("history", "institutional_commit_identity_reviewed"),
    ("history", "institutional_commit_identity_approved_for_publication"),
    ("history", "historical_local_path_reviewed"),
    ("history", "historical_local_path_approved_for_publication"),
    ("refs", "v0.1.0_retention_reviewed"),
    ("refs", "v0.1.0_retention_approved"),
    ("refs", "remote_branch_cleanup_reviewed"),
    ("refs", "local_unique_branch_reviewed"),
)


def check_maintainer_approvals(path: pathlib.Path, version: str) -> dict[str, Any]:
    if not path.is_file():
        return _check("maintainer_approvals", False, "ignored approval file is missing")
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return _check("maintainer_approvals", False, f"invalid approval file: {error}")
    missing = [
        f"{section}.{field}"
        for section, field in APPROVAL_FIELDS
        if (payload.get(section) or {}).get(field) is not True
    ]
    if payload.get("schema_version") != 1:
        missing.append("schema_version")
    if payload.get("release") != version:
        missing.append("release")
    if not str(payload.get("approved_by") or "").strip():
        missing.append("approved_by")
    try:
        _parse_timestamp(str(payload.get("approved_at") or ""))
    except ValueError:
        missing.append("approved_at")
    return _check(
        "maintainer_approvals",
        not missing,
        "approved" if not missing else "incomplete fields: " + ", ".join(missing),
    )


def check_source_bundle(root: pathlib.Path, image: str) -> dict[str, Any]:
    command = [
        "docker",
        "run",
        "--rm",
        image,
        "python",
        "-m",
        "scripts.verify_copyleft_r_sources",
        "--manifest",
        "/app/config/copyleft-r-sources.yaml",
        "--bundle-dir",
        "/usr/share/licenses/harako-rnaseq/sources/r",
        "--check-installed",
    ]
    result = _run(root, command)
    if result.returncode:
        return _check("r_corresponding_sources", False, result.stderr.strip()[-500:])
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        return _check("r_corresponding_sources", False, f"invalid verification output: {error}")
    passed = (
        payload.get("status") == "passed"
        and payload.get("verified_packages") == 10
        and not payload.get("unresolved")
    )
    return _check(
        "r_corresponding_sources",
        passed,
        f"verified={payload.get('verified_packages')}; unresolved={len(payload.get('unresolved') or [])}",
    )


def check_publication_state(
    visibility: str,
    publication_evidence: pathlib.Path | None,
    *,
    preparation: bool,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if visibility == "public":
        checks.append(_check("repository_visibility", True, "public"))
    elif preparation:
        checks.append(
            _check(
                "repository_visibility",
                True,
                "private repository is an expected manual gate",
                status="manual_gate",
            )
        )
    else:
        checks.append(_check("repository_visibility", False, visibility))
    evidence_passed = False
    if publication_evidence and publication_evidence.is_file():
        try:
            evidence = json.loads(publication_evidence.read_text("utf-8"))
            evidence_passed = bool(
                evidence.get("status") == "passed"
                and evidence.get("image_digest")
                and evidence.get("sbom")
                and evidence.get("provenance")
                and evidence.get("attestation")
                and evidence.get("github_prerelease_url")
            )
        except (OSError, json.JSONDecodeError):
            evidence_passed = False
    if evidence_passed:
        checks.append(_check("publication_evidence", True, "complete"))
    elif preparation:
        checks.append(
            _check(
                "publication_evidence",
                True,
                "publication is an expected manual gate",
                status="manual_gate",
            )
        )
    else:
        checks.append(_check("publication_evidence", False, "missing or incomplete"))
    return checks


def run_candidate_checks(
    root: pathlib.Path,
    version: str,
    expected_tag: str,
    image: str,
    allow_missing_tag: bool,
    *,
    approval_file: pathlib.Path | None = None,
    vulnerability_summary: pathlib.Path | None = None,
    repository_visibility: str = "private",
    publication_evidence: pathlib.Path | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    status = _run(root, ["git", "status", "--short"])
    checks.append(_check("working_tree_clean", status.returncode == 0 and not status.stdout.strip(), status.stdout.strip()))
    missing = [path for path in REQUIRED_FILES if not (root / path).is_file()]
    checks.append(_check("required_release_files", not missing, ", ".join(missing)))
    checks.extend(check_version_consistency(root, version, expected_tag, image))

    manifest = yaml.safe_load((root / "workflow" / "ref_manifest.yaml").read_text("utf-8"))
    hashes = []
    for releases in manifest.get("presets", {}).values():
        for release in releases.values():
            hashes.extend((release.get("sha256") or {}).values())
    checks.append(
        _check(
            "reference_hashes",
            len(hashes) == 12 and all(HASH_RE.fullmatch(str(value)) for value in hashes),
            f"{len(hashes)} hashes",
        )
    )

    checks.append(
        _report_check(
            "history_audit",
            root / "output/release-audit/git-history-audit.json",
            allowed_statuses={"clean", "clean_with_review"},
        )
    )
    checks.append(
        _report_check(
            "license_review",
            root / "output/release-audit/sbom-license-review.json",
            allowed_statuses={"passed"},
        )
    )
    checks.append(
        check_vulnerability_evidence(
            root,
            image,
            vulnerability_summary or root / "output/release-audit/trivy-summary.json",
        )
    )
    checks.append(check_source_bundle(root, image))
    checks.append(
        check_maintainer_approvals(
            approval_file or root / "output/release-audit/maintainer-approvals.json",
            version,
        )
    )

    tracked = _run(
        root,
        [
            "git",
            "ls-files",
            "output",
            "data",
            "data_in",
            "data_out",
            "out_smoke",
            "out_smoke_real",
        ],
    ).stdout.splitlines()
    generated = [path for path in tracked if not path.endswith(".gitkeep")]
    checks.append(_check("generated_data_untracked", not generated, ", ".join(generated)))

    with tempfile.TemporaryDirectory() as temp_dir:
        readiness_report = pathlib.Path(temp_dir) / "readiness.json"
        result = _run(
            root,
            [
                sys.executable,
                "scripts/check_release_readiness.py",
                "--version",
                version,
                "--for-image",
                image,
                "--public-beta-candidate",
                "--vulnerability-summary",
                str(vulnerability_summary or root / "output/release-audit/trivy-summary.json"),
                "--approval-file",
                str(approval_file or root / "output/release-audit/maintainer-approvals.json"),
                "--json-report",
                str(readiness_report),
                "--strict",
            ],
        )
        detail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr.strip()
        checks.append(_check("release_readiness", result.returncode == 0, detail))

    notes = (root / "docs" / "releases" / f"v{version}.md").read_text("utf-8")
    required_notes = (
        "QC-only",
        "Ensembl",
        "TBD after publication",
        "linux/amd64",
        "PolyForm Noncommercial",
    )
    checks.append(
        _check(
            "release_notes_complete",
            all(value in notes for value in required_notes),
            ", ".join(value for value in required_notes if value not in notes),
        )
    )
    checks.append(
        tag_check(root, expected_tag, allow_missing_tag, require_annotated=not allow_missing_tag)
    )
    checks.extend(
        check_publication_state(
            repository_visibility,
            publication_evidence,
            preparation=allow_missing_tag,
        )
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-tag", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--json-report", type=pathlib.Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-missing-tag", action="store_true")
    parser.add_argument(
        "--approval-file",
        type=pathlib.Path,
        default=ROOT / "output/release-audit/maintainer-approvals.json",
    )
    parser.add_argument(
        "--vulnerability-summary",
        type=pathlib.Path,
        default=ROOT / "output/release-audit/trivy-summary.json",
    )
    parser.add_argument(
        "--repository-visibility",
        choices=("private", "public"),
        default="private",
    )
    parser.add_argument("--publication-evidence", type=pathlib.Path)
    args = parser.parse_args()

    checks = run_candidate_checks(
        ROOT,
        args.version,
        args.expected_tag,
        args.image,
        args.allow_missing_tag,
        approval_file=args.approval_file,
        vulnerability_summary=args.vulnerability_summary,
        repository_visibility=args.repository_visibility,
        publication_evidence=args.publication_evidence,
    )
    failed = [item for item in checks if item["status"] == "fail"]
    manual = [item for item in checks if item["status"] == "manual_gate"]
    payload = {
        "schema_version": 1,
        "version": args.version,
        "expected_tag": args.expected_tag,
        "image": args.image,
        "network_used": False,
        "git_mutated": False,
        "status": "blocked" if failed else "prepared_with_manual_gates" if manual else "passed",
        "checks": checks,
    }
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    for item in checks:
        print(f"[{item['status'].upper()}] {item['name']}: {item['detail']}")
    return 1 if args.strict and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
