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
        ROOT, "0.2.0-beta.1", "v0.2.0-beta.1"
    )
    assert checks
    assert all(item["passed"] for item in checks), checks


def test_version_consistency_rejects_wrong_tag():
    checks = candidate.check_version_consistency(ROOT, "0.2.0-beta.1", "v0.2.1")
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


def test_release_notes_have_required_beta_markers():
    text = (ROOT / "docs" / "releases" / "v0.2.0-beta.1.md").read_text("utf-8")
    for marker in (
        "TBD after publication",
        "QC-only",
        "linux/amd64",
        "PolyForm Noncommercial",
        "not yet verified",
    ):
        assert marker in text
