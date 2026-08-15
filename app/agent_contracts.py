"""Versioned serialization and hashing contracts for the agent CLI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .core.canonical import canonical_json, sha256_payload
from .version import VERSION


AGENT_SCHEMA_VERSION = 1
AGENT_INTERFACE_VERSION = "1"
PLAN_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "config" / "schemas" / "harako-agent-plan-v1.schema.json"


class AgentInterfaceError(ValueError):
    """A safe error that can be returned through the machine-readable CLI."""


def response(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": AGENT_SCHEMA_VERSION,
        "harako_version": VERSION,
        **(payload or {}),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def execution_payload(plan: dict[str, Any]) -> dict[str, Any]:
    """Return every execution-relevant plan value and no display-only metadata."""
    payload = {
        "schema_version": plan.get("schema_version"),
        "harako_version": plan.get("harako_version"),
        "input_root": plan.get("input_root"),
        "output_root": plan.get("output_root"),
        "project_name": plan.get("project_name"),
        "samples": plan.get("samples"),
        "reference": plan.get("reference"),
        "analysis_plan": plan.get("analysis_plan"),
        "contrasts": plan.get("contrasts"),
        "enrichment": plan.get("enrichment"),
        "resources": plan.get("resources"),
        "requested_options": plan.get("requested_options"),
    }
    if "library_protocol" in plan:
        payload["library_protocol"] = plan.get("library_protocol")
    return payload


def plan_id_for(plan_or_payload: dict[str, Any]) -> str:
    payload = execution_payload(plan_or_payload) if "schema_version" in plan_or_payload else plan_or_payload
    return sha256_payload({"kind": "harako-agent-plan", "payload": payload})


def approval_hash_for(plan: dict[str, Any]) -> str:
    return sha256_payload({"kind": "harako-agent-approval", "payload": execution_payload(plan)})


def load_document(path: Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        text = source.read_text(encoding="utf-8")
        payload = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise AgentInterfaceError(f"Cannot read agent document: {exc}") from exc
    if not isinstance(payload, dict):
        raise AgentInterfaceError("Agent document must contain an object at the top level.")
    return payload


def write_document(path: Path, payload: dict[str, Any], *, force: bool = False) -> Path:
    destination = Path(path).expanduser().resolve()
    if destination.exists() and not force:
        raise AgentInterfaceError(f"Output already exists; use --force: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".json":
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    else:
        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    destination.write_text(text, encoding="utf-8")
    return destination


def schema_errors(plan: dict[str, Any]) -> list[str]:
    try:
        schema = json.loads(PLAN_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot load agent plan schema: {exc}"]
    validator = Draft202012Validator(schema)
    return sorted(
        f"schema {'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(plan)
    )
