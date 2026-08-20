from __future__ import annotations

import subprocess
import re
from pathlib import Path

import pytest
import yaml

from scripts import check_r_integration_stack as r_stack
from tests.git_helpers import tracked_paths


ROOT = Path(__file__).resolve().parents[1]


def test_r_stack_reports_missing_rscript():
    status = r_stack.probe_r_integration_stack(which=lambda _name: None)
    assert status.available is False
    assert status.reason_code == "rscript_missing"


def test_r_stack_reports_missing_required_package():
    def runner(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 2, "", "")

    status = r_stack.probe_r_integration_stack(
        which=lambda _name: "/usr/bin/Rscript",
        runner=runner,
    )
    assert status.available is False
    assert status.reason_code == "r_packages_missing"


def test_r_stack_preflight_fails_when_stack_is_absent(monkeypatch):
    unavailable = r_stack.RIntegrationStack(False, "rscript_missing", None)
    monkeypatch.setattr(r_stack, "r_integration_stack", lambda: unavailable)
    assert r_stack.main([]) == 1


def test_r_stack_declares_packages_used_by_real_fixture():
    assert r_stack.REQUIRED_R_PACKAGES == (
        "DESeq2",
        "dplyr",
        "ggplot2",
        "jsonlite",
        "readr",
        "rmarkdown",
        "yaml",
    )


def test_docker_ci_preflight_is_mandatory():
    workflow = (ROOT / ".github/workflows/docker-ci.yml").read_text(encoding="utf-8")
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")
    command = "python scripts/check_r_integration_stack.py"
    assert command in workflow
    assert command in justfile


def test_reference_manifest_retains_twelve_pinned_sha256_values():
    manifest = yaml.safe_load((ROOT / "workflow/ref_manifest.yaml").read_text(encoding="utf-8"))
    values = [
        digest
        for releases in manifest["presets"].values()
        for release in releases.values()
        for digest in release["sha256"].values()
    ]
    assert len(values) == 12
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in values)


def test_git_helper_uses_only_exact_command_scope_safe_directory(tmp_path):
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0, "", "")

    tracked_paths(tmp_path, "*.tar.gz", runner=runner)
    root = str(tmp_path.resolve())
    assert calls == [
        [
            "git",
            "-c",
            f"safe.directory={root}",
            "-C",
            root,
            "ls-files",
            "--",
            "*.tar.gz",
        ]
    ]
    assert "safe.directory=" + "*" not in " ".join(calls[0])


def test_git_helper_preserves_git_failures(tmp_path):
    def runner(command, **_kwargs):
        raise subprocess.CalledProcessError(128, command, stderr="synthetic failure")

    with pytest.raises(RuntimeError, match="synthetic failure"):
        tracked_paths(tmp_path, runner=runner)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_git_helper_detects_tracked_archives_and_audit_output(tmp_path):
    _git(tmp_path, "init", "-q")
    archive = tmp_path / "source.tar.gz"
    report = tmp_path / "output" / "release-audit" / "report.json"
    archive.write_bytes(b"fixture")
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")
    _git(tmp_path, "add", "source.tar.gz", "output/release-audit/report.json")

    assert tracked_paths(tmp_path, "*.tar.gz") == ["source.tar.gz"]
    assert tracked_paths(tmp_path, "output/release-audit") == [
        "output/release-audit/report.json"
    ]


def test_no_wildcard_safe_directory_is_configured():
    wildcard = "safe.directory=" + "*"
    for relative_path in tracked_paths(ROOT):
        path = ROOT / relative_path
        if path.is_file():
            assert wildcard not in path.read_text(
                encoding="utf-8", errors="ignore"
            )
