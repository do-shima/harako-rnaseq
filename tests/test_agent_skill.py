from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "harako-rnaseq-analysis" / "SKILL.md"
OPENAI_METADATA = SKILL.parent / "agents" / "openai.yaml"
CLAUDE_SKILL = ROOT / ".claude" / "skills" / "harako-rnaseq-analysis" / "SKILL.md"

COMMANDS = (
    "inspect-input",
    "propose-samples",
    "plan",
    "validate-plan",
    "dry-run",
    "execute",
    "status",
    "artifacts",
    "context",
    "post-analysis-init",
)

EXPECTED_REFERENCE_HASHES = {
    "34f848e2dd9c2a4e30d6ff2c7918a3e06c51fe1716c1e955e71e0c36ce28d5ad",
    "d8c3af0094a7bba6125763bad779ec18a81483c739c6ed122094bdf86c187b92",
    "62f1709b40e083ce9d4cdc64a86b5ffec2c5d5371434bb7095c74dc89079c466",
    "eafd274cdf83d440432ce6d2eccc34571b00cd966bcd5f84bd1fe17bbb8e54ae",
    "c661d19cfdbbee7ffbafa9bffb44581c6306480b9fef7b70e1d9c173782d370f",
    "b9fb3539f9883ae1c4b38a4e26d61e8a5367d59b175edf74fb2dadf0866840cf",
    "2947b18c23ca387ca5509a298c8feaa09b719c0110852851892e973da60ff655",
    "285bc481d583ab65b13d91853bf743acf950710afb3302264a4b4f116b6049c1",
    "8321415404aaf788c7da79774488ff227ac006d09a57ce6c616573a510338f64",
    "379c3ad238f12169fd397398c77aaff5435ec23bca74324bb8a886bd26511b09",
    "9e0cd229e1f0bc3c93e104c394a17ded4d30ef8acf30e6e4f6692a04c8160920",
    "402aefe269ecccba845a8a03137304af4356455c83b77453f799001974b4eb7c",
}


def _skill_parts() -> tuple[dict[str, str], str, str]:
    text = SKILL.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    assert match is not None
    return yaml.safe_load(match.group(1)), match.group(2), text


def test_canonical_skill_metadata_commands_and_size():
    metadata, body, text = _skill_parts()
    assert metadata["name"] == "harako-rnaseq-analysis"
    assert "explicit library-protocol selection" in metadata["description"]
    assert "approval-controlled execution" in metadata["description"]
    assert len(text.splitlines()) < 150
    assert all(command in body for command in COMMANDS)
    assert "run-plan" not in body
    assert "init-post-analysis" not in body
    assert "\\" not in text


def test_canonical_skill_scientific_and_approval_boundaries():
    _, body, _ = _skill_parts()
    assert "full_length" in body and "three_prime_tag" in body
    assert "Never infer biological conditions" in body
    assert "Never infer full-length versus 3′-tag protocol" in body
    assert "dry run is not execution approval" in body
    assert "exact current approval hash" in body
    assert "generic yes flag" in body
    assert "QC-only output as evidence of differential expression" in body
    assert "post-analysis-init" in body and "core outputs as read-only" in body
    assert "Old schema-v1 agent plans without `library_protocol`" in body
    assert "not executable" in body and "must be regenerated" in body
    assert "legacy_unspecified" in body


def test_skill_has_no_agent_runtime_dependency_or_secret_instruction():
    _, body, _ = _skill_parts()
    assert "Do not build or require an MCP server" in body
    for forbidden in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "sk-ant-", "sk-proj-"):
        assert forbidden not in body
    dependency_text = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("requirements.in", "requirements.lock.txt")
    ).lower()
    assert not re.search(r"(?m)^(openai|anthropic)\s*[=<>]", dependency_text)


def test_codex_metadata_and_claude_wrapper_use_one_contract():
    metadata = yaml.safe_load(OPENAI_METADATA.read_text(encoding="utf-8"))["interface"]
    assert metadata == {
        "display_name": "Harako RNA-seq Analysis",
        "short_description": "Plan and run local Harako RNA-seq with explicit approval",
        "default_prompt": (
            "Use $harako-rnaseq-analysis to inspect FASTQ pairing, obtain explicit "
            "condition and library-protocol assignments, build and validate a Harako "
            "plan, run a dry run, and stop for my approval before execution."
        ),
    }

    wrapper = CLAUDE_SKILL.read_text(encoding="utf-8")
    assert "../../../.agents/skills/harako-rnaseq-analysis/SKILL.md" in wrapper
    assert "never infer conditions" in wrapper
    assert "never infer it" in wrapper
    assert "dry run as validation only, not approval" in wrapper
    assert "exact current approval hash" in wrapper
    assert "core outputs as read-only" in wrapper
    assert wrapper.count("## Workflow") == 0


def test_documented_probe_contracts_stop_safely():
    _, body, _ = _skill_parts()
    assert body.index("inspect-input") < body.index("dry-run") < body.index("execute")
    assert "Ask the user to provide or confirm every sample-to-condition assignment" in body
    assert "Never infer biological conditions" in body
    assert "historical agent plan" in body
    assert "must be regenerated before\n  dry run or execution" in body


def test_all_reference_sha256_values_are_unchanged():
    manifest = yaml.safe_load((ROOT / "workflow" / "ref_manifest.yaml").read_text(encoding="utf-8"))
    hashes = {
        value
        for releases in manifest["presets"].values()
        for release in releases.values()
        for value in release["sha256"].values()
    }
    assert hashes == EXPECTED_REFERENCE_HASHES
