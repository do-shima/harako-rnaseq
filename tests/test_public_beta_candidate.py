from pathlib import Path

from typer.testing import CliRunner

from app.cli import app
from app.version import VERSION
from scripts import check_public_beta_candidate as candidate


ROOT = Path(__file__).resolve().parents[1]


def test_application_version_option():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == VERSION


def test_repository_version_values_are_consistent():
    checks = candidate.check_version_consistency(
        ROOT, "0.3.0-beta.2", "v0.3.0-beta.2"
    )
    assert checks
    assert all(item["passed"] for item in checks), checks


def test_version_consistency_rejects_wrong_tag():
    checks = candidate.check_version_consistency(ROOT, "0.3.0-beta.2", "v0.3.1")
    tag = next(item for item in checks if item["name"] == "expected_tag")
    assert tag["passed"] is False


def test_missing_tag_is_manual_gate_only_when_allowed(monkeypatch):
    class Result:
        returncode = 1

    monkeypatch.setattr(candidate, "_run", lambda *_args, **_kwargs: Result())
    allowed = candidate.tag_check(ROOT, "v9.9.9", True)
    blocked = candidate.tag_check(ROOT, "v9.9.9", False)
    assert allowed["status"] == "manual_gate"
    assert allowed["passed"] is True
    assert blocked["status"] == "fail"


def test_already_public_repository_does_not_repeat_visibility_transition_approval(tmp_path):
    public = candidate.check_release_approval_gate(
        tmp_path / "missing.json", "0.3.0-beta.2", "public", root=ROOT
    )
    private = candidate.check_release_approval_gate(
        tmp_path / "missing.json", "0.3.0-beta.2", "private", root=ROOT
    )
    assert public["passed"] is True
    assert "already-public" in public["detail"]
    assert private["passed"] is False


def test_release_notes_have_required_beta_markers():
    text = (ROOT / "docs" / "releases" / "v0.3.0-beta.2.md").read_text("utf-8")
    for marker in (
        "Release date: 2026-08-15",
        "ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.2",
        "No `latest` tag is published for this prerelease.",
        "gh attestation verify",
        "QC-only",
        "linux/amd64",
        "PolyForm Noncommercial",
        "Image availability begins only after",
    ):
        assert marker in text


def test_beta2_release_notes_recommend_full_length_reanalysis_without_overclaiming():
    text = (ROOT / "docs" / "releases" / "v0.3.0-beta.2.md").read_text("utf-8")
    assert "full-length RNA-seq with v0.3.0-beta.1 should rerun" in text
    assert "does not mean that every beta.1 result was incorrect" in text
    assert "TPM is an abundance output and is never used as DESeq2 model input" in text
