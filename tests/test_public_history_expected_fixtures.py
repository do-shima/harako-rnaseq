from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import pytest
import yaml

from scripts import audit_public_git_history as audit
from scripts import check_public_beta_candidate as candidate
from scripts.release_approvals import validate_history_audit_report


RELEASE = "0.2.0-beta.1"
REGISTRY_PATH = pathlib.Path("config/public-history-expected-fixtures.yaml")


def git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def credential(password: str = "reviewed_secret_y82") -> str:
    return (
        "https"
        + "://"
        + "reviewed_account_x91"
        + ":"
        + password
        + "@"
        + "example.invalid/repo"
    )


def line_for(value: str, prefix: str = "INVALID_REPOSITORY = ") -> bytes:
    return f'{prefix}"{value}"\n'.encode()


def init_repo(tmp_path: pathlib.Path, *, registry: bool = True) -> pathlib.Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@users.noreply.github.com")
    (root / "README.md").write_text("fixture\n", "utf-8")
    if registry:
        target = root / REGISTRY_PATH
        target.parent.mkdir(parents=True)
        target.write_text("schema_version: 1\nfixtures: []\n", "utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "initialize fixture")
    return root


def commit_file(root: pathlib.Path, path: str, content: bytes, message: str) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    git(root, "add", path)
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", f"HEAD:{path}")


def fingerprints(content: bytes) -> tuple[str, str]:
    match = audit.SECRET_PATTERNS["credential_url"].search(content)
    assert match is not None
    normalized_line = audit._normalized_line(content, match.start(), match.end())
    return (
        hashlib.sha256(match.group(0)).hexdigest(),
        hashlib.sha256(normalized_line).hexdigest(),
    )


def fixture_row(
    path: str,
    content: bytes,
    blobs: list[str],
    *,
    fixture_id: str = "registered_negative_fixture",
    category: str = "credential_url",
) -> dict[str, object]:
    match_sha, line_sha = fingerprints(content)
    return {
        "id": fixture_id,
        "finding_category": category,
        "repository_path": path,
        "match_sha256": match_sha,
        "source_line_sha256": line_sha,
        "blob_shas": blobs,
        "reason_code": "negative_validation_fixture",
        "rationale": "Synthetic invalid input used to verify credential rejection.",
        "reviewed_for_release": RELEASE,
    }


def write_registry(
    root: pathlib.Path,
    fixtures: list[dict[str, object]],
    *,
    commit: bool = True,
) -> None:
    target = root / REGISTRY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "fixtures": fixtures},
            sort_keys=False,
        ),
        "utf-8",
    )
    if commit:
        git(root, "add", REGISTRY_PATH.as_posix())
        git(root, "commit", "-m", "register reviewed fixture")


def registered_repo(
    tmp_path: pathlib.Path,
    *,
    path: str = "tests/negative_case.py",
    content: bytes | None = None,
) -> tuple[pathlib.Path, str, bytes]:
    root = init_repo(tmp_path)
    fixture_content = content or line_for(credential())
    blob = commit_file(root, path, fixture_content, "add negative validation fixture")
    write_registry(root, [fixture_row(path, fixture_content, [blob])])
    return root, blob, fixture_content


def test_exact_registered_fixture_is_nonblocking(tmp_path):
    root, _, _ = registered_repo(tmp_path)
    payload, _ = audit.audit_repository(root)
    assert payload["status"] == "clean_with_review"
    assert payload["credential_detector_findings"] == 1
    assert payload["expected_fixture_count"] == 1
    assert payload["actual_credential_blockers"] == 0
    assert payload["public_release_blockers"] == 0
    finding = next(
        item
        for item in payload["findings"]
        if item.get("fixture_status") == "expected_fixture"
    )
    assert finding["classification"] == "expected fixture/example"
    assert finding["detector_matched"] is True


def test_historical_and_current_blobs_must_both_be_reviewed(tmp_path):
    root = init_repo(tmp_path)
    path = "tests/negative_case.py"
    fixture_line = line_for(credential())
    first = commit_file(root, path, fixture_line + b"VERSION = 1\n", "fixture v1")
    second = commit_file(root, path, fixture_line + b"VERSION = 2\n", "fixture v2")
    write_registry(root, [fixture_row(path, fixture_line, [first, second])])
    payload, _ = audit.audit_repository(root)
    assert payload["credential_detector_findings"] == 2
    assert payload["expected_fixture_count"] == 2
    assert payload["public_release_blockers"] == 0


def test_audit_output_is_fingerprinted_and_redacted(tmp_path):
    root, _, content = registered_repo(tmp_path)
    payload, _ = audit.audit_repository(root)
    encoded = json.dumps(payload, sort_keys=True).encode()
    match = audit.SECRET_PATTERNS["credential_url"].search(content)
    assert match is not None
    raw = match.group(0)
    components = raw.split(b"://", 1)[1].rsplit(b"@", 1)[0].split(b":", 1)
    assert raw not in encoded
    assert all(component not in encoded for component in components)
    assert payload["expected_fixture_count"] == 1
    finding = next(
        item
        for item in payload["findings"]
        if item.get("fixture_status") == "expected_fixture"
    )
    assert len(finding["match_sha256"]) == 64
    assert len(finding["source_line_sha256"]) == 64


@pytest.mark.parametrize(
    "other_path",
    ["docs/copied.md", "tests/another_negative_case.py"],
)
def test_same_value_at_another_path_remains_blocking(tmp_path, other_path):
    root, _, content = registered_repo(tmp_path)
    commit_file(root, other_path, content, "copy unregistered credential fixture")
    payload, _ = audit.audit_repository(root)
    assert payload["actual_credential_blockers"] >= 1
    assert payload["public_release_blockers"] >= 1


def test_one_character_change_requires_review(tmp_path):
    root, _, _ = registered_repo(tmp_path)
    commit_file(
        root,
        "tests/negative_case.py",
        line_for(credential("synthetiX")),
        "change fixture",
    )
    payload, _ = audit.audit_repository(root)
    assert payload["expected_fixture_count"] == 1
    assert payload["actual_credential_blockers"] == 1


def test_source_line_change_requires_review(tmp_path):
    root, _, content = registered_repo(tmp_path)
    value = credential()
    changed = line_for(value, prefix="CHANGED_INVALID_REPOSITORY = ")
    assert fingerprints(content)[0] == fingerprints(changed)[0]
    assert fingerprints(content)[1] != fingerprints(changed)[1]
    commit_file(root, "tests/negative_case.py", changed, "change fixture line")
    payload, _ = audit.audit_repository(root)
    assert payload["actual_credential_blockers"] == 1


def test_different_registered_category_is_invalid(tmp_path):
    root = init_repo(tmp_path)
    path = "tests/negative_case.py"
    content = line_for(credential())
    blob = commit_file(root, path, content, "add fixture")
    write_registry(root, [fixture_row(path, content, [blob], category="github_token")])
    payload, _ = audit.audit_repository(root)
    assert payload["fixture_registry"]["status"] == "invalid"
    assert payload["public_release_blockers"] >= 1


def test_additional_credential_in_registered_file_blocks(tmp_path):
    root, _, content = registered_repo(tmp_path)
    changed = content + line_for(credential("additional"))
    commit_file(root, "tests/negative_case.py", changed, "add unregistered fixture")
    payload, _ = audit.audit_repository(root)
    assert payload["actual_credential_blockers"] == 2


@pytest.mark.parametrize(
    ("path", "password"),
    [
        ("tests/placeholder.py", "placeholder"),
        ("tests/example_domain.py", "example"),
        ("tests/token_shape.py", "ghp_" + "A" * 32),
        ("docs/example.md", "synthetic"),
    ],
)
def test_unregistered_credential_like_values_always_block(tmp_path, path, password):
    root = init_repo(tmp_path)
    commit_file(root, path, line_for(credential(password)), "add unregistered value")
    payload, _ = audit.audit_repository(root)
    assert payload["actual_credential_blockers"] >= 1
    assert payload["status"] == "blocked"


def valid_registry_row() -> dict[str, object]:
    content = line_for(credential())
    return fixture_row("tests/negative_case.py", content, ["1" * 40])


def load_registry_document(
    tmp_path: pathlib.Path, payload: object | None, *, raw: bytes | None = None
) -> audit.FixtureRegistry:
    path = tmp_path / "registry.yaml"
    if raw is not None:
        path.write_bytes(raw)
    elif payload is not None:
        path.write_text(yaml.safe_dump(payload, sort_keys=False), "utf-8")
    return audit.load_fixture_registry(tmp_path, path)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["fixtures"][0].__setitem__(
            "repository_path", "tests/*"
        ),
        lambda payload: payload["fixtures"][0].__setitem__(
            "match_sha256", "not-a-sha"
        ),
        lambda payload: payload["fixtures"][0].pop("rationale"),
        lambda payload: payload.__setitem__("schema_version", 2),
    ],
)
def test_invalid_registry_metadata_is_rejected(tmp_path, mutator):
    payload = {"schema_version": 1, "fixtures": [valid_registry_row()]}
    mutator(payload)
    assert load_registry_document(tmp_path, payload).valid is False


def test_duplicate_fixture_id_is_rejected(tmp_path):
    first = valid_registry_row()
    second = dict(first)
    second["repository_path"] = "tests/other.py"
    assert (
        load_registry_document(
            tmp_path, {"schema_version": 1, "fixtures": [first, second]}
        ).valid
        is False
    )


def test_duplicate_fixture_tuple_is_rejected(tmp_path):
    first = valid_registry_row()
    second = dict(first)
    second["id"] = "different_id"
    assert (
        load_registry_document(
            tmp_path, {"schema_version": 1, "fixtures": [first, second]}
        ).valid
        is False
    )


def test_registry_containing_raw_credential_syntax_is_rejected(tmp_path):
    raw_value = credential()
    raw = (
        "schema_version: 1\nfixtures: []\n"
        + "forbidden: "
        + raw_value
        + "\n"
    ).encode()
    result = load_registry_document(tmp_path, None, raw=raw)
    assert result.valid is False
    assert "registry.raw_credential_url" in result.error_codes


def test_missing_and_malformed_registry_are_rejected(tmp_path):
    missing = audit.load_fixture_registry(tmp_path, tmp_path / "missing.yaml")
    malformed = load_registry_document(tmp_path, None, raw=b"fixtures: [")
    assert missing.valid is False
    assert malformed.valid is False


def test_missing_registry_blocks_audit(tmp_path):
    root = init_repo(tmp_path, registry=False)
    payload, _ = audit.audit_repository(root)
    assert payload["fixture_registry"]["status"] == "invalid"
    assert payload["public_release_blockers"] == 1


def test_deleted_registered_fixture_remains_reviewed_in_history(tmp_path):
    root, _, _ = registered_repo(tmp_path)
    (root / "tests/negative_case.py").unlink()
    git(root, "add", "-u")
    git(root, "commit", "-m", "remove fixture")
    payload, _ = audit.audit_repository(root)
    assert payload["expected_fixture_count"] == 1
    assert payload["public_release_blockers"] == 0


def test_deleted_unregistered_credential_remains_blocking(tmp_path):
    root = init_repo(tmp_path)
    path = "tests/unregistered.py"
    commit_file(root, path, line_for(credential()), "add unregistered fixture")
    (root / path).unlink()
    git(root, "add", "-u")
    git(root, "commit", "-m", "remove unregistered fixture")
    payload, _ = audit.audit_repository(root)
    assert payload["actual_credential_blockers"] == 1


def test_candidate_and_readiness_accept_exact_fixture_report(tmp_path):
    root, _, _ = registered_repo(tmp_path)
    payload, _ = audit.audit_repository(root)
    report = tmp_path / "audit.json"
    report.write_text(json.dumps(payload), "utf-8")
    candidate_result = candidate.check_history_audit(report)
    readiness_passed, readiness_errors = validate_history_audit_report(report)
    assert candidate_result["passed"] is True
    assert readiness_passed is True
    assert readiness_errors == []


def test_candidate_and_readiness_reject_additional_credential(tmp_path):
    root, _, _ = registered_repo(tmp_path)
    commit_file(
        root,
        "tests/unregistered.py",
        line_for(credential("additional")),
        "add blocker",
    )
    payload, _ = audit.audit_repository(root)
    report = tmp_path / "audit.json"
    report.write_text(json.dumps(payload), "utf-8")
    assert candidate.check_history_audit(report)["passed"] is False
    assert validate_history_audit_report(report)[0] is False
