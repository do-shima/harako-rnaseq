"""Validate maintainer approvals and independently verified history removal."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


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
DEFAULT_EXPECTED_REPOSITORY = "github.com/do-shima/harako-rnaseq"
SCP_GITHUB_RE = re.compile(
    r"^(?P<user>[^@/:]+)@github\.com:(?P<path>[^?#]+)$", re.IGNORECASE
)


@dataclass(frozen=True)
class RepositoryScopeResult:
    ok: bool
    mode: str
    local_heads: tuple[str, ...]
    local_tags: tuple[str, ...]
    remote_tracking_heads: tuple[str, ...]
    symbolic_remote_head: str | None
    configured_remotes: dict[str, tuple[str, ...]]
    expected_repository: str
    reason_codes: tuple[str, ...]


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


def normalize_repository_identity(value: str) -> str:
    """Normalize an approved GitHub repository URL without network access."""
    candidate = value.strip()
    if not candidate or "?" in candidate or "#" in candidate:
        raise ValueError("repository URL cannot be empty or contain query/fragment")

    scp_match = SCP_GITHUB_RE.fullmatch(candidate)
    if scp_match:
        if scp_match.group("user").lower() != "git":
            raise ValueError("unsupported GitHub SSH user")
        path = scp_match.group("path")
    elif "://" not in candidate and candidate.lower().startswith("github.com/"):
        path = candidate[len("github.com/") :]
    else:
        parsed = urlsplit(candidate)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("invalid repository URL port") from error
        if scheme == "https":
            if host != "github.com" or port is not None:
                raise ValueError("unsupported HTTPS repository host")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("embedded repository credentials are forbidden")
        elif scheme == "ssh":
            valid_endpoint = (
                (host == "github.com" and port is None)
                or (host == "ssh.github.com" and port == 443)
            )
            if not valid_endpoint or parsed.username != "git" or parsed.password:
                raise ValueError("unsupported SSH repository endpoint")
        else:
            raise ValueError("unsupported repository URL scheme")
        path = parsed.path.lstrip("/")

    if path.lower().endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("repository URL must identify one owner and repository")
    owner, repository = parts
    if any(part in {".", ".."} for part in parts):
        raise ValueError("invalid repository identity")
    return f"github.com/{owner.lower()}/{repository.lower()}"


def _configured_remotes(root: pathlib.Path) -> tuple[dict[str, tuple[str, ...]], bool]:
    names = _git(root, "remote")
    if names.returncode:
        return {}, False
    configured: dict[str, tuple[str, ...]] = {}
    for name in sorted(line.strip() for line in names.stdout.splitlines() if line.strip()):
        urls: list[str] = []
        for key in (f"remote.{name}.url", f"remote.{name}.pushurl"):
            result = _git(root, "config", "--get-all", key)
            if result.returncode not in (0, 1):
                return {}, False
            urls.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
        configured[name] = tuple(urls)
    return configured, True


def evaluate_repository_scope(
    root: pathlib.Path,
    expected_repository: str = DEFAULT_EXPECTED_REPOSITORY,
) -> RepositoryScopeResult:
    """Classify an offline Git checkout against the public main-only policy."""
    try:
        expected_identity = normalize_repository_identity(expected_repository)
    except ValueError:
        expected_identity = expected_repository
        expected_invalid = True
    else:
        expected_invalid = False

    refs = _git(root, "for-each-ref", "--format=%(refname)%09%(symref)")
    configured_remotes, remotes_available = _configured_remotes(root)
    if refs.returncode or not remotes_available:
        return RepositoryScopeResult(
            ok=False,
            mode="invalid",
            local_heads=(),
            local_tags=(),
            remote_tracking_heads=(),
            symbolic_remote_head=None,
            configured_remotes=configured_remotes,
            expected_repository=expected_identity,
            reason_codes=("ref_inventory_unavailable",),
        )

    ref_pairs: list[tuple[str, str]] = []
    for line in refs.stdout.splitlines():
        if not line:
            continue
        ref_name, _, symref = line.partition("\t")
        ref_pairs.append((ref_name, symref))

    local_heads = tuple(sorted(ref for ref, _ in ref_pairs if ref.startswith("refs/heads/")))
    local_tags = tuple(sorted(ref for ref, _ in ref_pairs if ref.startswith("refs/tags/")))
    remote_pairs = sorted(
        (ref, symref) for ref, symref in ref_pairs if ref.startswith("refs/remotes/")
    )
    symbolic_remote_head = next(
        (symref for ref, symref in remote_pairs if ref == "refs/remotes/origin/HEAD"),
        None,
    )
    remote_tracking_heads = tuple(
        ref for ref, _ in remote_pairs if ref != "refs/remotes/origin/HEAD"
    )
    classified = set(local_heads) | set(local_tags) | {ref for ref, _ in remote_pairs}
    unexpected_refs = tuple(sorted(ref for ref, _ in ref_pairs if ref not in classified))

    common_reasons: list[str] = []
    if expected_invalid:
        common_reasons.append("expected_repository_invalid")
    if local_heads != ("refs/heads/main",):
        common_reasons.append("local_heads")
    if local_tags:
        common_reasons.append("local_tags")
    if unexpected_refs:
        common_reasons.append("unexpected_refs")

    if (
        not common_reasons
        and not configured_remotes
        and not remote_pairs
    ):
        return RepositoryScopeResult(
            True,
            "isolated_candidate",
            local_heads,
            local_tags,
            remote_tracking_heads,
            symbolic_remote_head,
            configured_remotes,
            expected_identity,
            (),
        )

    reasons = list(common_reasons)
    if tuple(configured_remotes) != ("origin",):
        reasons.append("configured_remotes")
    origin_urls = configured_remotes.get("origin", ())
    if not origin_urls:
        reasons.append("origin_url_missing")
    else:
        for url in origin_urls:
            try:
                identity = normalize_repository_identity(url)
            except ValueError:
                reasons.append("origin_url_invalid")
                break
            if identity != expected_identity:
                reasons.append("origin_repository_mismatch")
                break
    if remote_tracking_heads != ("refs/remotes/origin/main",):
        reasons.append("remote_tracking_heads")
    origin_head_pair = next(
        (pair for pair in remote_pairs if pair[0] == "refs/remotes/origin/HEAD"),
        None,
    )
    if origin_head_pair and origin_head_pair[1] != "refs/remotes/origin/main":
        reasons.append("origin_head_target")
    if any(ref != "refs/remotes/origin/HEAD" and symref for ref, symref in remote_pairs):
        reasons.append("unexpected_remote_symref")

    unique_reasons = tuple(dict.fromkeys(reasons))
    if not unique_reasons:
        return RepositoryScopeResult(
            True,
            "fresh_verification_clone",
            local_heads,
            local_tags,
            remote_tracking_heads,
            symbolic_remote_head,
            configured_remotes,
            expected_identity,
            (),
        )
    return RepositoryScopeResult(
        False,
        "invalid",
        local_heads,
        local_tags,
        remote_tracking_heads,
        symbolic_remote_head,
        configured_remotes,
        expected_identity,
        unique_reasons,
    )


def validate_public_ref_inventory(
    root: pathlib.Path,
    expected_repository: str = DEFAULT_EXPECTED_REPOSITORY,
) -> tuple[bool, list[str]]:
    """Compatibility wrapper retaining the existing candidate error keys."""
    result = evaluate_repository_scope(root, expected_repository)
    errors: list[str] = []
    ref_reasons = {
        "ref_inventory_unavailable",
        "local_heads",
        "local_tags",
        "unexpected_refs",
        "remote_tracking_heads",
        "origin_head_target",
        "unexpected_remote_symref",
    }
    remote_reasons = {
        "expected_repository_invalid",
        "configured_remotes",
        "origin_url_missing",
        "origin_url_invalid",
        "origin_repository_mismatch",
    }
    if any(reason in ref_reasons for reason in result.reason_codes):
        errors.append("candidate.main_only_ref_scope")
    if any(reason in remote_reasons for reason in result.reason_codes):
        errors.append("candidate.live_remote")
    return result.ok, errors


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
