from __future__ import annotations

import pathlib
import subprocess

import pytest

from scripts import check_public_beta_candidate as candidate
from scripts import check_release_readiness as readiness
from scripts.release_approvals import (
    DEFAULT_EXPECTED_REPOSITORY,
    evaluate_repository_scope,
    normalize_repository_identity,
    validate_public_ref_inventory,
)


EXPECTED_HTTPS = "https://github.com/do-shima/harako-rnaseq.git"


def git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture()
def repository(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Scope Fixture")
    git(root, "config", "user.email", "scope@users.noreply.github.com")
    (root / "README.md").write_text("scope fixture\n", "utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "scope fixture")
    return root


def add_origin(
    root: pathlib.Path,
    url: str = EXPECTED_HTTPS,
    *,
    include_main: bool = True,
    include_head: bool = True,
) -> None:
    git(root, "remote", "add", "origin", url)
    if include_main:
        git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    if include_head:
        git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/do-shima/harako-rnaseq.git",
        "https://github.com/do-shima/harako-rnaseq",
        "git@github.com:do-shima/harako-rnaseq.git",
        "git@github.com:do-shima/harako-rnaseq",
        "ssh://git@github.com/do-shima/harako-rnaseq.git",
        "ssh://git@github.com/do-shima/harako-rnaseq",
        "ssh://git@ssh.github.com:443/do-shima/harako-rnaseq.git",
    ],
)
def test_expected_repository_url_forms_normalize(url: str):
    assert normalize_repository_identity(url) == DEFAULT_EXPECTED_REPOSITORY


def test_isolated_candidate_passes(repository: pathlib.Path):
    result = evaluate_repository_scope(repository)
    assert result.ok is True
    assert result.mode == "isolated_candidate"
    assert validate_public_ref_inventory(repository) == (True, [])


@pytest.mark.parametrize(
    "url",
    [
        EXPECTED_HTTPS,
        "git@github.com:do-shima/harako-rnaseq.git",
        "ssh://git@ssh.github.com:443/do-shima/harako-rnaseq.git",
    ],
)
def test_fresh_verification_clone_passes(repository: pathlib.Path, url: str):
    add_origin(repository, url)
    result = evaluate_repository_scope(repository)
    assert result.ok is True
    assert result.mode == "fresh_verification_clone"
    assert result.remote_tracking_heads == ("refs/remotes/origin/main",)
    assert result.symbolic_remote_head == "refs/remotes/origin/main"


def test_fresh_clone_without_origin_head_passes(repository: pathlib.Path):
    add_origin(repository, include_head=False)
    result = evaluate_repository_scope(repository)
    assert result.ok is True
    assert result.mode == "fresh_verification_clone"
    assert result.symbolic_remote_head is None


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda root: git(root, "branch", "other"), "local_heads"),
        (lambda root: git(root, "tag", "v0.1.0"), "local_tags"),
        (
            lambda root: git(
                root,
                "update-ref",
                "refs/remotes/origin/dependabot/docker/python-3.14-slim",
                "HEAD",
            ),
            "remote_tracking_heads",
        ),
        (
            lambda root: git(
                root, "update-ref", "refs/remotes/origin/codex/audit", "HEAD"
            ),
            "remote_tracking_heads",
        ),
        (
            lambda root: git(
                root, "update-ref", "refs/remotes/origin/release/beta", "HEAD"
            ),
            "remote_tracking_heads",
        ),
        (
            lambda root: git(root, "remote", "add", "upstream", EXPECTED_HTTPS),
            "configured_remotes",
        ),
    ],
)
def test_additional_refs_or_remotes_are_rejected(
    repository: pathlib.Path, mutation, reason: str
):
    add_origin(repository)
    mutation(repository)
    result = evaluate_repository_scope(repository)
    assert result.ok is False
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/other/harako-rnaseq.git",
        "https://github.com/do-shima/other.git",
        "https://github.com/do-shima/harako-rnaseq-private-archive.git",
        "https://user:token@github.com/do-shima/harako-rnaseq.git",
        "https://gitlab.com/do-shima/harako-rnaseq.git",
        "https://github.com/do-shima/harako-rnaseq.git?token=value",
        "ssh://git@github.com:22/do-shima/harako-rnaseq.git",
    ],
)
def test_unexpected_origin_urls_are_rejected(repository: pathlib.Path, url: str):
    add_origin(repository, url)
    result = evaluate_repository_scope(repository)
    assert result.ok is False
    assert any(
        reason in result.reason_codes
        for reason in ("origin_url_invalid", "origin_repository_mismatch")
    )
    assert "candidate.live_remote" in validate_public_ref_inventory(repository)[1]


def test_origin_head_must_target_origin_main(repository: pathlib.Path):
    add_origin(repository, include_head=False)
    git(repository, "update-ref", "refs/remotes/origin/other", "HEAD")
    git(
        repository,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/other",
    )
    result = evaluate_repository_scope(repository)
    assert result.ok is False
    assert "origin_head_target" in result.reason_codes


def test_remote_tracking_branch_without_origin_main_is_rejected(repository: pathlib.Path):
    add_origin(repository, include_main=False, include_head=False)
    git(repository, "update-ref", "refs/remotes/origin/other", "HEAD")
    result = evaluate_repository_scope(repository)
    assert result.ok is False
    assert "remote_tracking_heads" in result.reason_codes


@pytest.mark.parametrize("ref_name", ["refs/pull/1/head", "refs/replace/" + "1" * 40])
def test_pull_and_replace_refs_are_rejected(repository: pathlib.Path, ref_name: str):
    git(repository, "update-ref", ref_name, "HEAD")
    result = evaluate_repository_scope(repository)
    assert result.ok is False
    assert "unexpected_refs" in result.reason_codes


def test_candidate_and_readiness_use_the_same_scope_evaluator(
    repository: pathlib.Path,
):
    add_origin(repository)
    candidate_result = candidate.evaluate_repository_scope(repository)
    readiness_result = readiness.evaluate_repository_scope(repository)
    assert candidate_result.ok is True
    assert readiness_result.ok is True
    assert candidate_result.mode == readiness_result.mode == "fresh_verification_clone"


def test_dependabot_branch_remains_blocking_in_candidate_and_readiness(
    repository: pathlib.Path,
):
    add_origin(repository)
    git(
        repository,
        "update-ref",
        "refs/remotes/origin/dependabot/github_actions/actions",
        "HEAD",
    )
    assert candidate.evaluate_repository_scope(repository).ok is False
    assert readiness.evaluate_repository_scope(repository).ok is False


def test_scope_evaluator_does_not_invoke_network(monkeypatch, repository: pathlib.Path):
    add_origin(repository)
    observed: list[tuple[str, ...]] = []
    original = subprocess.run

    def recording_run(command, *args, **kwargs):
        if command[0] == "git":
            observed.append(tuple(command[1:]))
        return original(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    assert evaluate_repository_scope(repository).ok is True
    assert not any(args and args[0] in {"fetch", "pull", "ls-remote"} for args in observed)
