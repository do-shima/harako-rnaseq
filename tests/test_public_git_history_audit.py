from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import audit_public_git_history as audit


ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Fixture Maintainer")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    registry = repo / "config" / "public-history-expected-fixtures.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text("schema_version: 1\nfixtures: []\n", "utf-8")
    _git(repo, "add", registry.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "add fixture registry")
    return repo


def _commit(repo: Path, path: str, content: bytes, message: str = "fixture") -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    _git(repo, "add", path)
    _git(repo, "commit", "-m", message)


def test_clean_history_and_identity_inventory(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "README.md", b"# Fixture\n")
    payload, identities = audit.audit_repository(repo)
    assert payload["status"] == "clean"
    assert payload["reachable"]["reachable_object_count"] >= 3
    assert payload["identity_summary"]["unique_identity_count"] == 1
    assert (
        sum(payload["identity_summary"]["signature_status_counts"].values())
        == payload["identity_summary"]["commit_count"]
    )
    assert identities[0]["author_email"] == "fixture@example.invalid"
    assert "fixture@example.invalid" not in json.dumps(payload)


def test_secret_findings_are_redacted(tmp_path):
    repo = _repo(tmp_path)
    secret = "ghp_" + "A" * 32
    _commit(repo, "config.txt", f"token={secret}\n".encode())
    payload, _ = audit.audit_repository(repo)
    encoded = json.dumps(payload)
    assert payload["status"] == "blocked"
    assert "github_token" in encoded
    assert secret not in encoded
    assert "value redacted" in encoded


def test_large_deleted_blob_remains_reachable(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "asset.bin", b"x" * (audit.LARGE_BLOB + 1))
    (repo / "asset.bin").unlink()
    _git(repo, "add", "-u")
    _git(repo, "commit", "-m", "remove fixture")
    payload, _ = audit.audit_repository(repo)
    row = next(item for item in payload["reachable"]["largest_blobs"] if item["path"] == "asset.bin")
    assert row["size"] > audit.LARGE_BLOB
    assert row["present_in_head"] is False
    assert row["first_introducing_commit"]


def test_small_biological_fixture_is_expected(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "tests/data/reads.fastq", b"@r1\nACGT\n+\nIIII\n")
    payload, _ = audit.audit_repository(repo)
    assert any(
        item["classification"] == "expected fixture/example" for item in payload["findings"]
    )
    assert payload["status"] != "blocked"


def test_generic_documentation_home_path_is_not_private(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "docs/example.md", b"Use /home/user/data or C:\\Users\\example\\data.\n")
    payload, _ = audit.audit_repository(repo)
    assert not any(
        item["category"] in {"unix_home_path", "windows_user_path"}
        for item in payload["findings"]
    )


def test_cli_writes_sanitized_reports(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "README.md", b"# Fixture\n")
    json_report = tmp_path / "audit.json"
    text_report = tmp_path / "audit.txt"
    identities = tmp_path / "identities.tsv"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_public_git_history.py"),
            "--repo",
            str(repo),
            "--json-report",
            str(json_report),
            "--text-report",
            str(text_report),
            "--identity-report",
            str(identities),
            "--strict",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert json.loads(json_report.read_text("utf-8"))["status"] == "clean"
    assert "fixture@example.invalid" not in text_report.read_text("utf-8")
    assert "fixture@example.invalid" in identities.read_text("utf-8")
