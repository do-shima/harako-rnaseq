from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml

from scripts import check_release_readiness as release


ROOT = Path(__file__).resolve().parents[1]


def test_release_tag_policy_accepts_stable_and_beta_only():
    assert release.TAG_RE.fullmatch("v0.2.0")
    assert release.TAG_RE.fullmatch("v0.2.0-beta.1")
    for value in ("0.2.0", "v0.2", "v0.2.0-rc.1", "latest", "main"):
        assert not release.TAG_RE.fullmatch(value)


def test_citation_validates_against_vendored_official_schema():
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "config" / "cff-schema-1.2.0.json").read_text("utf-8"))
    jsonschema.validate(citation, schema)
    assert citation["version"] == "0.2.0-beta.1"
    assert citation["license"] == "PolyForm-Noncommercial-1.0.0"


def test_license_and_governance_yaml_are_release_ready():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "PolyForm Noncommercial License 1.0.0" in license_text
    assert "https://polyformproject.org/licenses/noncommercial/1.0.0" in license_text
    assert "Required Notice: Copyright 2026 Daisuke Ohshima" in license_text
    assert "<REPLACE_WITH_" not in license_text

    templates = sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))
    assert {path.name for path in templates} == {
        "bug_report.yml",
        "config.yml",
        "documentation.yml",
        "feature_request.yml",
    }
    assert all(yaml.safe_load(path.read_text(encoding="utf-8")) for path in templates)


def test_strict_source_release_readiness_passes(tmp_path):
    report = tmp_path / "release.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_release_readiness.py"),
            "--version",
            "0.2.0-beta.1",
            "--json-report",
            str(report),
            "--strict",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert all(item["passed"] for item in payload["checks"])


def test_version_mismatch_fails_in_strict_mode():
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_release_readiness.py"),
            "--version",
            "0.2.0",
            "--strict",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "[FAIL] citation_version" in completed.stdout


def test_all_twelve_reference_hashes_are_valid():
    manifest = yaml.safe_load((ROOT / "workflow" / "ref_manifest.yaml").read_text("utf-8"))
    hashes = [
        digest
        for releases in manifest["presets"].values()
        for entry in releases.values()
        for digest in entry["sha256"].values()
    ]
    assert len(hashes) == 12
    assert all(release.HASH_RE.fullmatch(value) for value in hashes)
