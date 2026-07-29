from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_beta_feedback_template_is_valid_and_private_by_design():
    path = ROOT / ".github" / "ISSUE_TEMPLATE" / "beta_feedback.yml"
    payload = yaml.safe_load(path.read_text("utf-8"))
    assert payload["name"] == "Public-beta feedback"
    ids = {
        item.get("id")
        for item in payload["body"]
        if isinstance(item, dict) and item.get("id")
    }
    assert {
        "platform",
        "docker_version",
        "input_type",
        "read_layout",
        "reference",
        "scale",
        "report_completed",
        "failed_step",
        "elapsed",
        "disk",
        "usability",
        "documentation",
        "support_bundle",
        "privacy",
    } <= ids
    text = path.read_text("utf-8").lower()
    for prohibited in ("fastq", "patient", "credentials", "identifiable sample", "confidential"):
        assert prohibited in text


def test_release_notes_have_finalized_publication_metadata():
    path = ROOT / "docs" / "releases" / "v0.2.0-beta.1.md"
    text = path.read_text("utf-8")
    for marker in (
        "Release date: 2026-07-29",
        "ghcr.io/do-shima/harako-rnaseq:v0.2.0-beta.1",
        "ghcr.io/do-shima/harako-rnaseq:beta",
        "No `latest` tag is published for this prerelease.",
        "gh attestation verify",
        "Image availability begins only after",
    ):
        assert marker in text
    assert "TBD after publication" not in text
    assert "DOI" not in text


def test_launch_runbook_contains_manual_gates_and_exact_tag_commands():
    text = (ROOT / "docs" / "public-beta-launch-runbook.md").read_text("utf-8")
    for value in (
        "approve author/committer identity inventory",
        "git tag -a v0.2.0-beta.1",
        "git push origin v0.2.0-beta.1",
        "python-tests",
        "windows-path-tests",
        "governance-docs",
        "docker-tests",
        "no `latest` tag",
        "5–10 users",
        "three unaided report completions",
    ):
        assert value.lower() in text.lower()


def test_phase5_document_links_resolve():
    paths = (
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "beta-feedback.md",
        ROOT / "docs" / "transitive-license-review.md",
        ROOT / "docs" / "vulnerability-review-v0.2.0-beta.1.md",
        ROOT / "docs" / "public-beta-launch-runbook.md",
        ROOT / "docs" / "releases" / "v0.2.0-beta.1.md",
    )
    import re

    link_re = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
    for source in paths:
        assert source.is_file()
        for raw in link_re.findall(source.read_text("utf-8")):
            split = urlsplit(raw.strip().strip("<>"))
            if not split.path or split.scheme or split.netloc or raw.startswith("#"):
                continue
            target = (source.parent / unquote(split.path)).resolve()
            assert target.exists(), f"{source.relative_to(ROOT)} -> {raw}"


def test_vulnerability_review_records_scan_without_security_claim():
    text = (ROOT / "docs" / "vulnerability-review-v0.2.0-beta.1.md").read_text("utf-8")
    assert "Trivy" in text
    assert "| Critical |" in text
    assert "not a security certification" in text
    assert "config/vulnerability-dispositions-v0.2.0-beta.1.json" in text


def test_ci_host_python_is_overridable_for_windows():
    text = (ROOT / "justfile").read_text("utf-8")
    assert 'PYTHON := env_var_or_default("PYTHON", "python")' in text
    block = text.split("ci-host:", 1)[1].split("ci-docker:", 1)[0]
    assert block.count('"{{PYTHON}}"') == 3
