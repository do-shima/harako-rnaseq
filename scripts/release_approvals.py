"""Validate maintainer approvals and independently verified history removal."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
from typing import Any


HASH_RE = re.compile(r"^[0-9a-f]{64}$")
PRIVATE_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:\\Users\\[^\\\r\n]+\\|/(?:home|Users)/[^/\r\n]+/)"
)
LEGACY_FIELDS = (
    ("history", "institutional_commit_identity_reviewed"),
    ("history", "institutional_commit_identity_approved_for_publication"),
    ("history", "historical_local_path_reviewed"),
    ("history", "historical_local_path_approved_for_publication"),
    ("refs", "v0.1.0_retention_reviewed"),
    ("refs", "v0.1.0_retention_approved"),
    ("refs", "remote_branch_cleanup_reviewed"),
    ("refs", "local_unique_branch_reviewed"),
)
HISTORY_PATH_CATEGORIES = {"windows_user_path", "unix_home_path", "unc_path"}


def _parse_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _load_json(path: pathlib.Path, label: str, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"{label}.missing")
        return {}
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append(f"{label}.invalid")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"{label}.invalid")
        return {}
    return payload


def _contains_private_path(value: Any) -> bool:
    if isinstance(value, str):
        return PRIVATE_PATH_RE.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_private_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_private_path(item) for item in value)
    return False


def _git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )


def validate_public_ref_inventory(root: pathlib.Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    refs = _git(root, "for-each-ref", "--format=%(refname)")
    if refs.returncode:
        return False, ["candidate.ref_inventory_unavailable"]
    ref_names = sorted(line for line in refs.stdout.splitlines() if line)
    if ref_names != ["refs/heads/main"]:
        errors.append("candidate.main_only_ref_scope")
    remotes = _git(root, "remote")
    if remotes.returncode or remotes.stdout.strip():
        errors.append("candidate.live_remote")
    return not errors, errors


def _validate_common(payload: dict[str, Any], release: str, errors: list[str]) -> None:
    if payload.get("release") != release:
        errors.append("release")
    if not str(payload.get("approved_by") or "").strip():
        errors.append("approved_by")
    try:
        _parse_timestamp(str(payload.get("approved_at") or ""))
    except ValueError:
        errors.append("approved_at")


def _validate_schema1(payload: dict[str, Any], errors: list[str]) -> None:
    for section, field in LEGACY_FIELDS:
        if (payload.get(section) or {}).get(field) is not True:
            errors.append(f"{section}.{field}")


def _validate_public_scope(payload: dict[str, Any], errors: list[str]) -> None:
    scope = payload.get("public_ref_scope") or {}
    expected = {
        "reviewed": True,
        "publish_main_only": True,
        "include_existing_tags": False,
        "include_merged_codex_branches": False,
        "include_unique_local_branches": False,
        "v0.1.0_disposition": "private_archive_only",
    }
    for field, value in expected.items():
        if scope.get(field) != value:
            errors.append(f"public_ref_scope.{field}")


def _validate_history_audit(path: pathlib.Path, errors: list[str]) -> None:
    audit = _load_json(path, "history_audit", errors)
    if not audit:
        return
    if audit.get("status") not in {"clean", "clean_with_review"}:
        errors.append("history_audit.status")
    for finding in audit.get("findings") or []:
        if finding.get("classification") == "public-release blocker":
            errors.append("history_audit.public_release_blocker")
            break
    for finding in audit.get("findings") or []:
        if finding.get("category") in HISTORY_PATH_CATEGORIES:
            errors.append("history_audit.local_path_occurrence")
            break


def _validate_zero_report(path: pathlib.Path, errors: list[str]) -> None:
    report = _load_json(path, "zero_occurrence_report", errors)
    if not report:
        return
    if report.get("status") != "pass":
        errors.append("zero_occurrence_report.status")
    if report.get("total_sensitive_occurrences") != 0:
        errors.append("zero_occurrence_report.total_sensitive_occurrences")
    if report.get("old_sensitive_blob_reachable") is not False:
        errors.append("zero_occurrence_report.old_sensitive_blob_reachable")


def _validate_removal_evidence(
    payload: dict[str, Any],
    root: pathlib.Path,
    evidence_path: pathlib.Path,
    history_audit_path: pathlib.Path,
    zero_report_path: pathlib.Path,
    errors: list[str],
) -> None:
    history = payload.get("history") or {}
    evidence = _load_json(evidence_path, "history_rewrite_evidence", errors)
    if not evidence:
        return
    if _contains_private_path(evidence):
        errors.append("history_rewrite_evidence.raw_private_path")
    if evidence.get("raw_sensitive_value_in_report") is not False:
        errors.append("history_rewrite_evidence.raw_sensitive_value_in_report")

    expected_hash = str(history.get("history_rewrite_evidence_sha256") or "")
    actual_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    if not HASH_RE.fullmatch(expected_hash) or expected_hash != actual_hash:
        errors.append("history.history_rewrite_evidence_sha256")

    base_commit = str(history.get("rewritten_base_commit") or "")
    base_tree = str(history.get("rewritten_base_tree") or "")
    if evidence.get("rewritten_main_commit") != base_commit:
        errors.append("history.rewritten_base_commit")
    if evidence.get("rewritten_main_tree") != base_tree:
        errors.append("history.rewritten_base_tree")
    if (evidence.get("zero_occurrence") or {}).get("count") != 0:
        errors.append("history_rewrite_evidence.zero_occurrence")
    if (evidence.get("post_rewrite_audit") or {}).get("public_release_blockers") != 0:
        errors.append("history_rewrite_evidence.public_release_blockers")
    if (evidence.get("post_rewrite_audit") or {}).get("local_path_findings") != 0:
        errors.append("history_rewrite_evidence.local_path_findings")

    base_exists = _git(root, "cat-file", "-e", f"{base_commit}^{{commit}}")
    if base_exists.returncode:
        errors.append("candidate.rewritten_base_commit_missing")
    else:
        ancestry = _git(root, "merge-base", "--is-ancestor", base_commit, "HEAD")
        if ancestry.returncode:
            errors.append("candidate.rewritten_base_not_ancestor")
        tree = _git(root, "rev-parse", f"{base_commit}^{{tree}}")
        if tree.returncode or tree.stdout.strip() != base_tree:
            errors.append("candidate.rewritten_base_tree")

    reachable = set(
        line.split(" ", 1)[0]
        for line in _git(root, "rev-list", "--objects", "--all").stdout.splitlines()
        if line
    )
    old_commit = str(evidence.get("affected_old_commit") or "")
    old_blob = str(evidence.get("affected_old_blob") or "")
    if not old_commit or old_commit in reachable:
        errors.append("candidate.old_affected_commit_reachable")
    if not old_blob or old_blob in reachable:
        errors.append("candidate.old_affected_blob_reachable")

    _validate_history_audit(history_audit_path, errors)
    _validate_zero_report(zero_report_path, errors)


def validate_maintainer_approvals(
    path: pathlib.Path,
    release: str,
    *,
    root: pathlib.Path,
    require_schema2: bool = False,
    evidence_path: pathlib.Path | None = None,
    history_audit_path: pathlib.Path | None = None,
    zero_report_path: pathlib.Path | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    payload = _load_json(path, "approval_file", errors)
    if not payload:
        return False, errors
    _validate_common(payload, release, errors)

    schema = payload.get("schema_version")
    if schema == 1:
        _validate_schema1(payload, errors)
        if require_schema2:
            errors.append("schema_version.2_required")
        return not errors, errors
    if schema != 2:
        errors.append("schema_version")
        return False, errors

    history = payload.get("history") or {}
    for field in (
        "institutional_commit_identity_reviewed",
        "institutional_commit_identity_approved_for_publication",
        "historical_local_path_reviewed",
    ):
        if history.get(field) is not True:
            errors.append(f"history.{field}")

    disclosure_approved = history.get(
        "historical_local_path_approved_for_publication"
    ) is True
    removal_verified = (
        history.get("historical_local_path_approved_for_publication") is False
        and history.get("historical_local_path_removed_verified") is True
    )
    if not disclosure_approved and not removal_verified:
        errors.append("history.disclosure_or_verified_removal")

    _validate_public_scope(payload, errors)
    if removal_verified:
        _validate_removal_evidence(
            payload,
            root,
            evidence_path
            or root
            / "output/release-audit/history-rewrite/history-rewrite-verification.json",
            history_audit_path or root / "output/release-audit/git-history-audit.json",
            zero_report_path
            or root
            / "output/release-audit/history-rewrite/candidate-zero-occurrence.json",
            errors,
        )
    return not errors, errors
