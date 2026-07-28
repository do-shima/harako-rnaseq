from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from scripts import check_public_beta_candidate as candidate
from scripts import create_release_approval_template as approvals


ROOT = Path(__file__).resolve().parents[1]


def approval_payload() -> dict:
    return {
        "schema_version": 1,
        "release": "0.2.0-beta.1",
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
        "approved_by": "maintainer",
        "approved_at": "2026-07-28T12:00:00+09:00",
        "notes": "",
    }


def test_missing_and_incomplete_approvals_are_blocking(tmp_path):
    missing = candidate.check_maintainer_approvals(tmp_path / "missing.json", "0.2.0-beta.1")
    assert missing["passed"] is False
    path = tmp_path / "approvals.json"
    payload = approval_payload()
    payload["history"]["historical_local_path_approved_for_publication"] = False
    path.write_text(json.dumps(payload), "utf-8")
    result = candidate.check_maintainer_approvals(path, "0.2.0-beta.1")
    assert result["passed"] is False
    assert "historical_local_path_approved_for_publication" in result["detail"]


def test_approver_and_iso_timestamp_are_required(tmp_path):
    path = tmp_path / "approvals.json"
    payload = approval_payload()
    payload["approved_by"] = ""
    payload["approved_at"] = "not-a-time"
    path.write_text(json.dumps(payload), "utf-8")
    result = candidate.check_maintainer_approvals(path, "0.2.0-beta.1")
    assert result["passed"] is False
    assert "approved_by" in result["detail"]
    assert "approved_at" in result["detail"]


def test_fully_explicit_approval_passes_without_disclosing_values(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text(json.dumps(approval_payload()), "utf-8")
    result = candidate.check_maintainer_approvals(path, "0.2.0-beta.1")
    assert result["passed"] is True
    assert result["detail"] == "approved"


def test_tracked_example_contains_no_private_identity_or_path():
    path = ROOT / "config" / "release-approvals.example.json"
    payload = json.loads(path.read_text("utf-8"))
    text = path.read_text("utf-8")
    assert payload["history"]["institutional_commit_identity_approved_for_publication"] is True
    assert payload["history"]["historical_local_path_approved_for_publication"] is False
    assert "@" not in text
    assert "Users\\" not in text
    assert "/home/" not in text


def test_template_creation_preserves_existing_file(tmp_path):
    example = tmp_path / "example.json"
    output = tmp_path / "maintainer-approvals.json"
    example.write_text('{"approved": false}\n', "utf-8")
    assert approvals.create_template(example, output) is True
    output.write_text('{"approved": true}\n', "utf-8")
    assert approvals.create_template(example, output) is False
    assert json.loads(output.read_text("utf-8"))["approved"] is True


def test_stale_or_wrong_image_vulnerability_evidence_fails(tmp_path, monkeypatch):
    path = tmp_path / "summary.json"
    payload = {
        "status": "passed",
        "scan_timestamp": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat(),
        "scanner": {"verified_installation": True},
        "image": {"id": "sha256:wrong"},
        "counts": {"CRITICAL": 0, "HIGH": 0},
        "blocking_findings": [],
        "all_highs_dispositioned": True,
    }
    path.write_text(json.dumps(payload), "utf-8")

    class Result:
        returncode = 0
        stdout = json.dumps([{"Id": "sha256:expected"}])
        stderr = ""

    monkeypatch.setattr(candidate, "_run", lambda *_args, **_kwargs: Result())
    result = candidate.check_vulnerability_evidence(tmp_path, "image", path)
    assert result["passed"] is False
    assert "image_match=False" in result["detail"]


def test_preparation_allows_visibility_and_publication_as_manual_gates():
    checks = candidate.check_publication_state("private", None, preparation=True)
    assert all(item["status"] == "manual_gate" for item in checks)
    strict = candidate.check_publication_state("private", None, preparation=False)
    assert all(item["status"] == "fail" for item in strict)
