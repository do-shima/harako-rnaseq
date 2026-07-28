from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from scripts import install_verified_trivy as installer
from scripts import run_vulnerability_scan as scanner


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("version", ["0.69.4", "0.69.5", "0.69.6"])
def test_compromised_trivy_versions_are_rejected(version):
    with pytest.raises(ValueError, match="supply-chain"):
        installer.validate_version(version)


@pytest.mark.parametrize("version", ["latest", "vlatest", "main"])
def test_mutable_trivy_versions_are_rejected(version):
    with pytest.raises(ValueError, match="immutable"):
        installer.validate_version(version)


def test_reviewed_trivy_release_and_platform_assets():
    assert installer.validate_version("v0.70.0") == "0.70.0"
    assert installer.select_asset("0.70.0", "Windows", "AMD64") == (
        "trivy_0.70.0_windows-64bit.zip",
        "trivy.exe",
    )
    assert installer.select_asset("0.70.0", "Linux", "x86_64") == (
        "trivy_0.70.0_Linux-64bit.tar.gz",
        "trivy",
    )


def test_unverified_or_changed_scanner_is_rejected(tmp_path, monkeypatch):
    binary = tmp_path / "trivy"
    binary.write_bytes(b"verified")
    report = tmp_path / "installation.json"
    report.write_text(
        json.dumps(
            {
                "verified": False,
                "version": "0.70.0",
                "binary": str(binary),
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            }
        ),
        "utf-8",
    )
    with pytest.raises(ValueError, match="not verified"):
        scanner.verify_installation(report)

    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    payload = json.loads(report.read_text("utf-8"))
    payload.update({"verified": True, "binary": "trivy", "binary_sha256": "0" * 64})
    report.write_text(json.dumps(payload), "utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        scanner.verify_installation(report)


def _report(severity="LOW", fixed_version=""):
    return {
        "Results": [
            {
                "Target": "runtime",
                "Type": "debian",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-TEST-1",
                        "PkgName": "example",
                        "InstalledVersion": "1",
                        "FixedVersion": fixed_version,
                        "Severity": severity,
                    }
                ],
            }
        ]
    }


def test_vulnerability_policy_zero_or_low_findings_passes():
    counts, reviewed, blockers = scanner.evaluate_report(_report(), {})
    assert counts["LOW"] == 1
    assert reviewed == []
    assert blockers == []


def test_malformed_trivy_report_is_rejected():
    with pytest.raises(ValueError, match="Malformed Trivy report"):
        scanner.evaluate_report({}, {})


def test_critical_with_fix_is_blocking_until_fixed():
    key = "CVE-TEST-1|example|1"
    dispositions = {
        key: {
            "status": "accepted_for_beta",
            "rationale": "test rationale",
            "reachability": "test context",
        }
    }
    _, _, blockers = scanner.evaluate_report(_report("CRITICAL", "2"), dispositions)
    assert any("available fix" in item for item in blockers)
    dispositions[key]["status"] = "fixed"
    _, _, blockers = scanner.evaluate_report(_report("CRITICAL", "2"), dispositions)
    assert blockers == []


def test_high_requires_explicit_disposition():
    key = "CVE-TEST-1|example|1"
    _, reviewed, blockers = scanner.evaluate_report(_report("HIGH"), {})
    assert reviewed[0]["disposition"]["status"] == "release_blocker"
    assert blockers
    dispositions = {
        key: {
            "status": "accepted_for_beta",
            "rationale": "Not reachable in the local application path.",
            "reachability": "Installed but not invoked by Harako.",
        }
    }
    _, _, blockers = scanner.evaluate_report(_report("HIGH"), dispositions)
    assert blockers == []


def test_path_redaction():
    value = scanner._redact_text(str(ROOT / "private") + " C:\\Users\\Person\\secret")
    assert str(ROOT) not in value
    assert "Person" not in value


def test_vulnerability_workflow_is_pinned_and_cannot_publish():
    path = ROOT / ".github" / "workflows" / "vulnerability-scan.yml"
    text = path.read_text("utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert "pull_request_target" not in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    assert "packages: write" not in text
    assert "push: true" not in text
    assert "0.70.0" in text
    assert "trivy-version: latest" not in text.lower()
    assert "aquasecurity/trivy-action@latest" not in text.lower()
    assert (
        "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25"
        in text
    )
    assert "scripts/check_vulnerability_policy.py" in text


def test_candidate_dispositions_are_exact_and_explicit():
    path = ROOT / "config" / "vulnerability-dispositions-v0.2.0-beta.1.json"
    payload = json.loads(path.read_text("utf-8"))
    dispositions = payload["dispositions"]
    assert len(dispositions) == 93
    assert all("*" not in key and key.count("|") == 2 for key in dispositions)
    assert all(
        item["status"] in scanner.ALLOWED_DISPOSITIONS
        and item["rationale"].strip()
        and item["reachability"].strip()
        for item in dispositions.values()
    )
