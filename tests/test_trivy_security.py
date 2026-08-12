from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from scripts import install_verified_trivy as installer
from scripts import run_vulnerability_scan as scanner


ROOT = Path(__file__).resolve().parents[1]


def _workflow_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _workflow_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _workflow_values(child)
    else:
        yield str(value)


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
    steps = workflow["jobs"]["vulnerability-scan"]["steps"]
    assert "pull_request_target" not in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    assert "packages: write" not in text
    assert "push: true" not in text
    assert "platforms: linux/amd64" in text
    assert "load: true" not in text
    assert "outputs: type=docker,dest=${{ runner.temp }}/harako-rnaseq-vulnerability-scan.tar" in text
    assert "input: ${{ runner.temp }}/harako-rnaseq-vulnerability-scan.tar" in text
    assert "image-ref:" not in text
    assert "version: v0.70.0" in text
    assert "trivy-version:" not in text
    assert "ignore-unfixed" not in text
    assert "version: latest" not in text.lower()
    assert "aquasecurity/trivy:latest" not in text.lower()
    assert "aquasecurity/trivy-action@latest" not in text.lower()
    assert (
        "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25"
        in text
    )
    assert "scripts/check_vulnerability_policy.py" in text
    trivy_steps = [
        step
        for step in steps
        if step.get("uses", "").startswith("aquasecurity/trivy-action@")
    ]
    assert len(trivy_steps) == 1
    assert trivy_steps[0]["with"]["format"] == "json"
    assert trivy_steps[0]["with"]["scanners"] == "vuln"
    assert trivy_steps[0]["with"]["exit-code"] == "0"
    assert trivy_steps[0]["with"]["hide-progress"] == "true"
    assert trivy_steps[0]["with"]["cache"] == "true"
    assert trivy_steps[0]["with"]["cache-dir"] == "${{ runner.temp }}/trivy-cache"


def test_vulnerability_workflow_reclaims_disk_and_converts_without_rescan():
    path = ROOT / ".github" / "workflows" / "vulnerability-scan.yml"
    text = path.read_text("utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["vulnerability-scan"]["steps"]
    names = [step.get("name", "") for step in steps]

    build = names.index("Build linux/amd64 scan archive")
    reclaim = names.index("Verify archive and reclaim BuildKit storage")
    capacity = names.index("Verify disk capacity before scan")
    scan = names.index("Scan image as JSON")
    convert = names.index("Convert JSON report to SARIF")
    policy = names.index("Enforce reviewed Critical and High policy")
    upload = names.index("Upload sanitized scanner reports")
    cleanup = names.index("Remove ephemeral scan data")
    assert build < reclaim < capacity < scan < convert < policy < upload < cleanup

    assert text.count("docker buildx prune --all --force") >= 2
    assert "df -h" in text
    assert "df -i" in text
    assert "docker system df" in text
    assert "TRIVY_TMPDIR: ${{ runner.temp }}/trivy-tmp" in text
    assert "TMPDIR: ${{ runner.temp }}/trivy-tmp" in text
    assert "trivy_bin=$(command -v trivy)" in text
    assert '"$trivy_bin" convert --format sarif' in text
    assert 'sarif.get("version") != "2.1.0"' in text
    steps_by_name = {step.get("name"): step for step in steps}
    assert steps_by_name["Verify archive and reclaim BuildKit storage"]["env"] == {
        "IMAGE_ARCHIVE": "${{ runner.temp }}/harako-rnaseq-vulnerability-scan.tar"
    }
    assert steps_by_name["Verify disk capacity before scan"]["env"] == {
        "IMAGE_ARCHIVE": "${{ runner.temp }}/harako-rnaseq-vulnerability-scan.tar",
        "TRIVY_TMPDIR": "${{ runner.temp }}/trivy-tmp",
        "TRIVY_CACHE_DIR": "${{ runner.temp }}/trivy-cache",
        "JSON_REPORT": "output/release-audit/trivy-vulnerabilities.json",
    }
    assert steps_by_name["Convert JSON report to SARIF"]["env"] == {
        "TMPDIR": "${{ runner.temp }}/trivy-tmp",
        "JSON_REPORT": "output/release-audit/trivy-vulnerabilities.json",
        "SARIF_REPORT": "output/release-audit/trivy-vulnerabilities.sarif",
    }
    assert (
        "--report output/release-audit/trivy-vulnerabilities.json"
        in steps_by_name["Enforce reviewed Critical and High policy"]["run"]
    )
    assert steps[cleanup]["if"] == "always()"
    assert steps[cleanup]["env"] == {
        "IMAGE_ARCHIVE": "${{ runner.temp }}/harako-rnaseq-vulnerability-scan.tar",
        "TRIVY_TMPDIR": "${{ runner.temp }}/trivy-tmp",
        "TRIVY_CACHE_DIR": "${{ runner.temp }}/trivy-cache",
        "JSON_REPORT": "output/release-audit/trivy-vulnerabilities.json",
        "SARIF_REPORT": "output/release-audit/trivy-vulnerabilities.sarif",
    }
    assert "rm -f -- \"$IMAGE_ARCHIVE\"" in steps[cleanup]["run"]


def test_runner_context_paths_are_not_declared_in_job_level_env():
    workflow = yaml.load(
        (ROOT / ".github" / "workflows" / "vulnerability-scan.yml").read_text("utf-8"),
        Loader=yaml.BaseLoader,
    )
    job = workflow["jobs"]["vulnerability-scan"]
    assert "env" not in job

    for job_id, job_config in workflow["jobs"].items():
        job_env = job_config.get("env", {})
        values = tuple(_workflow_values(job_env))
        assert not any("${{ runner." in value for value in values), job_id
        assert not any("RUNNER_TEMP" in value for value in values), job_id

    steps = job["steps"]
    scan = next(step for step in steps if step.get("name") == "Scan image as JSON")
    assert scan["env"]["TMPDIR"] == "${{ runner.temp }}/trivy-tmp"
    assert (
        scan["with"]["input"]
        == "${{ runner.temp }}/harako-rnaseq-vulnerability-scan.tar"
    )
    assert scan["with"]["cache-dir"] == "${{ runner.temp }}/trivy-cache"


def test_vulnerability_workflow_never_uploads_the_image_archive():
    workflow = yaml.load(
        (ROOT / ".github" / "workflows" / "vulnerability-scan.yml").read_text("utf-8"),
        Loader=yaml.BaseLoader,
    )
    steps = workflow["jobs"]["vulnerability-scan"]["steps"]
    upload = next(step for step in steps if step.get("name") == "Upload sanitized scanner reports")
    uploaded = upload["with"]["path"]
    assert "harako-rnaseq-vulnerability-scan.tar" not in uploaded
    assert "trivy-vulnerabilities.json" in uploaded
    assert "trivy-vulnerabilities.sarif" in uploaded
    assert not any("free-disk-space" in step.get("uses", "") for step in steps)


@pytest.mark.parametrize("version", ["0.2.0-beta.1", "0.3.0-beta.1"])
def test_candidate_dispositions_are_exact_and_explicit(version):
    path = ROOT / "config" / f"vulnerability-dispositions-v{version}.json"
    payload = json.loads(path.read_text("utf-8"))
    assert payload["release"] == version
    dispositions = payload["dispositions"]
    assert len(dispositions) == 93
    assert all("*" not in key and key.count("|") == 2 for key in dispositions)
    assert all(
        item["status"] in scanner.ALLOWED_DISPOSITIONS
        and item["rationale"].strip()
        and item["reachability"].strip()
        for item in dispositions.values()
    )
