from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "pages.yml"
ACTION = re.compile(r"^\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def load_workflow() -> dict:
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_pages_workflow_uses_immutable_action_pins() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    actions = ACTION.findall(text)
    assert {name for name, _ in actions} == {
        "actions/checkout",
        "actions/configure-pages",
        "actions/upload-pages-artifact",
        "actions/deploy-pages",
    }
    assert all(FULL_SHA.fullmatch(revision) for _, revision in actions)
    for version in ("# v6.1.0", "# v5.0.0", "# v3.0.1", "# v4.0.5"):
        assert version in text


def test_pages_workflow_has_scoped_triggers_and_least_privilege() -> None:
    workflow = load_workflow()
    assert workflow["on"]["push"] == {
        "branches": ["main"],
        "paths": ["site/**", ".github/workflows/pages.yml"],
    }
    assert "workflow_dispatch" in workflow["on"]
    assert "pull_request_target" not in workflow["on"]
    assert workflow["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }


def test_pages_workflow_uploads_only_site_and_uses_no_repository_secret() -> None:
    workflow = load_workflow()
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    build_steps = workflow["jobs"]["build"]["steps"]
    upload = next(step for step in build_steps if "actions/upload-pages-artifact@" in step.get("uses", ""))
    assert upload["with"] == {"path": "site/"}
    assert "secrets." not in text
    assert "pull_request_target" not in text
    assert not any("run" in step for job in workflow["jobs"].values() for step in job["steps"])


def test_pages_deploys_through_github_pages_environment() -> None:
    workflow = load_workflow()
    deploy = workflow["jobs"]["deploy"]
    assert deploy["needs"] == "build"
    assert deploy["environment"]["name"] == "github-pages"
    assert deploy["environment"]["url"] == "${{ steps.deployment.outputs.page_url }}"
