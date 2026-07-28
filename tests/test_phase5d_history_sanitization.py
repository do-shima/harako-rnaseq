from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import pytest

from scripts import check_public_beta_candidate as candidate
from scripts.release_approvals import validate_public_ref_inventory


RELEASE = "0.2.0-beta.1"


def git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")


@pytest.fixture()
def sanitized_fixture(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@users.noreply.github.com")
    (root / "README.md").write_text("candidate\n", "utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "candidate base")
    base_commit = git(root, "rev-parse", "HEAD")
    base_tree = git(root, "rev-parse", "HEAD^{tree}")

    evidence_path = (
        root
        / "output/release-audit/history-rewrite/history-rewrite-verification.json"
    )
    evidence = {
        "schema_version": 1,
        "release": RELEASE,
        "affected_old_commit": "1" * 40,
        "affected_old_blob": "2" * 40,
        "rewritten_main_commit": base_commit,
        "rewritten_main_tree": base_tree,
        "main_tree_identical": True,
        "zero_occurrence": {"status": "pass", "count": 0},
        "post_rewrite_audit": {
            "status": "clean_with_review",
            "public_release_blockers": 0,
            "local_path_findings": 0,
        },
        "raw_sensitive_value_in_report": False,
    }
    write_json(evidence_path, evidence)

    audit_path = root / "output/release-audit/git-history-audit.json"
    write_json(
        audit_path,
        {
            "schema_version": 1,
            "status": "clean_with_review",
            "findings": [],
        },
    )
    zero_path = (
        root / "output/release-audit/history-rewrite/candidate-zero-occurrence.json"
    )
    write_json(
        zero_path,
        {
            "schema_version": 1,
            "status": "pass",
            "total_sensitive_occurrences": 0,
            "old_sensitive_blob_reachable": False,
        },
    )

    approval_path = root / "output/release-audit/maintainer-approvals.json"

    def save_approval() -> dict:
        payload = {
            "schema_version": 2,
            "release": RELEASE,
            "history": {
                "institutional_commit_identity_reviewed": True,
                "institutional_commit_identity_approved_for_publication": True,
                "historical_local_path_reviewed": True,
                "historical_local_path_approved_for_publication": False,
                "historical_local_path_removed_verified": True,
                "history_rewrite_evidence_sha256": hashlib.sha256(
                    evidence_path.read_bytes()
                ).hexdigest(),
                "rewritten_base_commit": base_commit,
                "rewritten_base_tree": base_tree,
            },
            "public_ref_scope": {
                "reviewed": True,
                "publish_main_only": True,
                "include_existing_tags": False,
                "include_merged_codex_branches": False,
                "include_unique_local_branches": False,
                "v0.1.0_disposition": "private_archive_only",
            },
            "approved_by": "Maintainer",
            "approved_at": "2026-07-28T05:00:00Z",
            "notes": "Verified removal fixture.",
        }
        write_json(approval_path, payload)
        return payload

    approval = save_approval()
    return {
        "root": root,
        "base_commit": base_commit,
        "base_tree": base_tree,
        "evidence": evidence,
        "evidence_path": evidence_path,
        "audit_path": audit_path,
        "zero_path": zero_path,
        "approval": approval,
        "approval_path": approval_path,
        "save_approval": save_approval,
    }


def check(fixture) -> dict:
    return candidate.check_maintainer_approvals(
        fixture["approval_path"],
        RELEASE,
        root=fixture["root"],
        require_schema2=True,
    )


def test_schema2_verified_removal_passes(sanitized_fixture):
    result = check(sanitized_fixture)
    assert result["passed"] is True
    assert validate_public_ref_inventory(sanitized_fixture["root"]) == (True, [])


def test_tracked_example_is_schema2_without_private_values():
    path = pathlib.Path(__file__).resolve().parents[1] / "config/release-approvals.example.json"
    payload = json.loads(path.read_text("utf-8"))
    text = path.read_text("utf-8")
    assert payload["schema_version"] == 2
    assert payload["history"]["historical_local_path_approved_for_publication"] is False
    assert payload["public_ref_scope"]["publish_main_only"] is True
    assert payload["public_ref_scope"]["include_existing_tags"] is False
    assert "@" not in text
    assert "Users\\" not in text
    assert "/home/" not in text


def test_missing_or_wrong_evidence_is_rejected(sanitized_fixture):
    sanitized_fixture["evidence_path"].unlink()
    assert check(sanitized_fixture)["passed"] is False
    write_json(sanitized_fixture["evidence_path"], sanitized_fixture["evidence"])
    sanitized_fixture["approval"]["history"]["history_rewrite_evidence_sha256"] = "0" * 64
    write_json(sanitized_fixture["approval_path"], sanitized_fixture["approval"])
    assert check(sanitized_fixture)["passed"] is False


@pytest.mark.parametrize("field", ["rewritten_base_commit", "rewritten_base_tree"])
def test_wrong_rewritten_base_is_rejected(sanitized_fixture, field):
    sanitized_fixture["approval"]["history"][field] = "3" * 40
    write_json(sanitized_fixture["approval_path"], sanitized_fixture["approval"])
    assert check(sanitized_fixture)["passed"] is False


def test_nonzero_occurrence_report_is_rejected(sanitized_fixture):
    zero = json.loads(sanitized_fixture["zero_path"].read_text("utf-8"))
    zero["total_sensitive_occurrences"] = 1
    write_json(sanitized_fixture["zero_path"], zero)
    assert check(sanitized_fixture)["passed"] is False


def test_reachable_old_commit_is_rejected(sanitized_fixture):
    sanitized_fixture["evidence"]["affected_old_commit"] = sanitized_fixture["base_commit"]
    write_json(sanitized_fixture["evidence_path"], sanitized_fixture["evidence"])
    sanitized_fixture["save_approval"]()
    assert check(sanitized_fixture)["passed"] is False


def test_schema1_remains_readable_but_is_insufficient_for_strict_release(tmp_path):
    path = tmp_path / "legacy.json"
    payload = {
        "schema_version": 1,
        "release": RELEASE,
        "history": {
            "institutional_commit_identity_reviewed": True,
            "institutional_commit_identity_approved_for_publication": True,
            "historical_local_path_reviewed": True,
            "historical_local_path_approved_for_publication": True,
        },
        "refs": {
            "v0.1.0_retention_reviewed": True,
            "v0.1.0_retention_approved": True,
            "remote_branch_cleanup_reviewed": True,
            "local_unique_branch_reviewed": True,
        },
        "approved_by": "Maintainer",
        "approved_at": "2026-07-28T05:00:00Z",
    }
    write_json(path, payload)
    assert candidate.check_maintainer_approvals(
        path, RELEASE, root=tmp_path
    )["passed"]
    strict = candidate.check_maintainer_approvals(
        path, RELEASE, root=tmp_path, require_schema2=True
    )
    assert strict["passed"] is False
    assert "schema_version.2_required" in strict["detail"]


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("publish_main_only", False),
        ("include_existing_tags", True),
        ("include_merged_codex_branches", True),
        ("include_unique_local_branches", True),
        ("v0.1.0_disposition", "publish"),
    ],
)
def test_public_scope_must_exclude_tags_and_private_branches(
    sanitized_fixture, field, bad_value
):
    sanitized_fixture["approval"]["public_ref_scope"][field] = bad_value
    write_json(sanitized_fixture["approval_path"], sanitized_fixture["approval"])
    assert check(sanitized_fixture)["passed"] is False


def test_ref_inventory_rejects_extra_tag_or_branch(sanitized_fixture):
    root = sanitized_fixture["root"]
    git(root, "tag", "unexpected")
    passed, errors = validate_public_ref_inventory(root)
    assert passed is False
    assert "candidate.main_only_ref_scope" in errors


def test_evidence_with_private_path_shape_is_rejected(sanitized_fixture):
    sanitized_fixture["evidence"]["forbidden_fixture"] = (
        "C:\\Users\\fixture\\private"
    )
    write_json(sanitized_fixture["evidence_path"], sanitized_fixture["evidence"])
    sanitized_fixture["save_approval"]()
    assert check(sanitized_fixture)["passed"] is False
