from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
ACTION = re.compile(r"^\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def workflow_texts() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in WORKFLOW_DIR.glob("*.yml")}


def load_workflow(name: str) -> dict:
    return yaml.load((WORKFLOW_DIR / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_workflow_yaml_parses_and_external_actions_are_immutable():
    texts = workflow_texts()
    assert {"ci.yml", "docker-ci.yml", "publish-image.yml"} <= set(texts)
    for name, text in texts.items():
        assert yaml.load(text, Loader=yaml.BaseLoader)
        for owner_action, revision in ACTION.findall(text):
            if owner_action.startswith("./"):
                continue
            assert FULL_SHA.fullmatch(revision), f"{name}: {owner_action}@{revision}"


def test_pr_workflows_are_read_only_and_never_use_pull_request_target():
    for name in ("ci.yml", "docker-ci.yml"):
        workflow = load_workflow(name)
        triggers = workflow["on"]
        assert "pull_request" in triggers
        assert "pull_request_target" not in triggers
        assert workflow["permissions"] == {"contents": "read"}
        assert workflow["concurrency"]["cancel-in-progress"] == "true"
        for job in workflow["jobs"].values():
            assert "timeout-minutes" in job
    all_text = "\n".join(workflow_texts().values())
    assert "pull_request_target" not in all_text
    assert "secrets.GITHUB_TOKEN" not in (
        (WORKFLOW_DIR / "ci.yml").read_text()
        + (WORKFLOW_DIR / "docker-ci.yml").read_text()
    )


def test_ci_has_stable_critical_job_names_and_commands():
    ci = load_workflow("ci.yml")
    assert {"python-tests", "windows-path-tests", "governance-docs"} <= set(ci["jobs"])
    docker = load_workflow("docker-ci.yml")
    assert "docker-tests" in docker["jobs"]
    text = "\n".join(workflow_texts().values())
    for command in (
        "python -m pytest -q",
        "test_i18n.py",
        "test_public_docs.py",
        "test_ref_manifest_presets.py",
        "just smoke",
        "just verify-smoke",
        "just doctor-ui",
    ):
        assert command in text


def test_publish_triggers_and_permissions_are_scoped():
    workflow = load_workflow("publish-image.yml")
    assert workflow["on"]["push"]["tags"] == ["v*"]
    assert "workflow_dispatch" in workflow["on"]
    readiness = workflow["jobs"]["release-readiness"]
    publish = workflow["jobs"]["publish"]
    assert readiness["permissions"] == {"contents": "read"}
    assert publish["permissions"]["packages"] == "write"
    assert publish["permissions"]["id-token"] == "write"
    assert publish["permissions"]["attestations"] == "write"
    assert publish["permissions"]["artifact-metadata"] == "write"
    assert "needs.release-readiness.outputs.publish == 'true'" in publish["if"]


def test_publication_policy_is_amd64_only_and_beta_never_gets_latest():
    text = (WORKFLOW_DIR / "publish-image.yml").read_text(encoding="utf-8")
    assert "ghcr.io/do-shima/harako-rnaseq" in text
    assert text.count("platforms: linux/amd64") == 2
    assert "setup-qemu" not in text
    assert "value=beta,enable=${{ contains(" in text
    assert "value=latest,enable=${{ !contains(" in text
    assert "sbom: true" in text
    assert "provenance: mode=max" in text
    assert "subject-digest: ${{ steps.push.outputs.digest }}" in text
    assert "subject-name: ghcr.io/do-shima/harako-rnaseq" in text
    assert "current visibility" in text


def test_docker_ci_never_pushes_and_uses_no_production_reference_download():
    text = (WORKFLOW_DIR / "docker-ci.yml").read_text(encoding="utf-8")
    assert "push: false" in text
    assert "login-action" not in text
    assert "--download-missing" not in text
    assert "output/refs_cache" in text

