"""Canonical agent planning and validation services."""

from __future__ import annotations

import os
import re
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from app.agent_contracts import (
    AGENT_SCHEMA_VERSION,
    AgentInterfaceError,
    approval_hash_for,
    load_document,
    plan_id_for,
    response,
    schema_errors,
    utc_now,
)
from app.core.analysis import AnalysisPlanError, assert_analysis_plan_consistent, evaluate_analysis_eligibility
from app.core.protocol import resolve_library_protocol
from app.reference_presets import (
    build_reference_provenance,
    get_release_entry,
    resolve_existing_cache_paths,
    validate_builtin_manifest,
)
from app.services.agent_inputs import SAMPLE_COLUMNS, read_sample_table, validate_sample_rows
from app.services.configuration import resolve_reference_config
from app.version import VERSION


SCHEMA_VERSION = AGENT_SCHEMA_VERSION
PROJECT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
FORBIDDEN_PLAN_KEYS = {"command", "commands", "shell", "argv", "script", "executable_path"}

def _analysis_plan(rows: list[dict[str, str]]) -> dict[str, Any]:
    return evaluate_analysis_eligibility(rows).to_plan()


def _resolve_contrasts(
    analysis: dict[str, Any], levels: list[str], mode: str, reference: str | None, selected: list[list[str]] | None
) -> tuple[dict[str, Any], list[str]]:
    unresolved: list[str] = []
    if analysis["mode"] != "differential":
        return {"mode": None, "reference": None, "pairs": [], "active": False}, unresolved
    if mode == "ref":
        if not reference:
            unresolved.append("A contrast reference is required for differential mode.")
            pairs: list[list[str]] = []
        elif reference not in levels:
            unresolved.append(f"Contrast reference '{reference}' is not a sample condition.")
            pairs = []
        else:
            pairs = [[level, reference] for level in levels if level != reference]
        return {"mode": mode, "reference": reference, "pairs": pairs, "active": not unresolved}, unresolved
    if mode == "pairwise":
        pairs = [[left, right] for left, right in combinations(levels, 2)]
        return {"mode": mode, "reference": None, "pairs": pairs, "active": bool(pairs)}, unresolved
    if mode == "select":
        pairs = selected or []
        for pair in pairs:
            if len(pair) != 2 or pair[0] == pair[1] or any(level not in levels for level in pair):
                unresolved.append(f"Invalid selected contrast: {pair}")
        return {"mode": mode, "reference": None, "pairs": pairs, "active": bool(pairs) and not unresolved}, unresolved
    unresolved.append(f"Unsupported contrast mode: {mode}")
    return {"mode": mode, "reference": reference, "pairs": [], "active": False}, unresolved


def create_plan(
    *,
    sample_table: Path,
    species: str,
    ref_preset: str,
    contrast_ref: str | None,
    output_root: Path,
    input_root: Path | None = None,
    project_name: str = "harako",
    library_protocol: str,
    contrast_mode: str = "ref",
    contrast_pairs: list[list[str]] | None = None,
    ref_release: str = "pinned",
    ref_cache_dir: Path | None = None,
    ref_manifest: Path | None = None,
    enable_enrichment: bool = False,
    threads: int = 1,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    table = Path(sample_table).expanduser().resolve()
    if input_root:
        root = Path(input_root).expanduser().resolve()
    else:
        raw_rows = read_sample_table(table)
        absolute_fastqs = [Path(row[key]).expanduser() for row in raw_rows for key in ("fastq1", "fastq2") if row.get(key)]
        root = Path(os.path.commonpath([str(path.resolve()) for path in absolute_fastqs])).resolve() if absolute_fastqs and all(path.is_absolute() for path in absolute_fastqs) else table.parent.resolve()
        if root.is_file():
            root = root.parent
    output = Path(output_root).expanduser().resolve()
    if not PROJECT_RE.fullmatch(project_name):
        raise AgentInterfaceError("project_name may contain only letters, numbers, underscores, and hyphens.")
    try:
        library_protocol = resolve_library_protocol(library_protocol)
    except ValueError as exc:
        raise AgentInterfaceError(str(exc)) from exc
    rows = read_sample_table(table)
    errors, warnings, unresolved, normalized_rows = validate_sample_rows(rows, root, allow_missing_conditions=True)
    if errors:
        raise AgentInterfaceError("; ".join(errors))
    analysis = _analysis_plan(normalized_rows)

    manifest_path = (ref_manifest or Path(__file__).resolve().parents[1] / "workflow" / "ref_manifest.yaml").resolve()
    cache_dir = (ref_cache_dir or output / "refs_cache").resolve()
    resolved_cfg = resolve_reference_config(
        {
            "species": species.strip().lower(),
            "output": str(output),
            "ref_manifest": str(manifest_path),
            "ref_cache_dir": str(cache_dir),
            "ref_preset": ref_preset,
            "ref_release": ref_release,
        },
        str(table),
    )
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    metadata = (manifest.get("preset_metadata") or {}).get(resolved_cfg["ref_preset"], {})
    provenance = dict(resolved_cfg.get("reference_provenance") or {})
    reference = {
        "species": species.strip().lower(),
        "requested_preset": ref_preset,
        "canonical_preset": resolved_cfg["ref_preset"],
        "release": resolved_cfg["ref_release"],
        "assembly": metadata.get("assembly"),
        "manifest_path": str(manifest_path),
        "cache_dir": str(cache_dir),
        "expected_paths": dict((resolved_cfg.get("ref") or {}).get(species.strip().lower()) or {}),
        "checksum_verified": bool(provenance.get("checksum_verified")),
        "provenance": provenance,
    }
    if not reference["checksum_verified"]:
        unresolved.append("Selected reference files are absent or not checksum-verified.")

    levels = sorted(analysis.get("condition_counts") or {})
    contrasts, contrast_unresolved = _resolve_contrasts(analysis, levels, contrast_mode, contrast_ref, contrast_pairs)
    unresolved.extend(contrast_unresolved)
    enrichment_eligible = bool(analysis.get("enrichment_allowed"))
    enrichment = {
        "requested": bool(enable_enrichment),
        "enabled": bool(enable_enrichment and enrichment_eligible),
        "eligible": enrichment_eligible,
    }
    if enable_enrichment and not enrichment_eligible:
        warnings.append("Enrichment was requested but is inactive because inferential DE is unavailable.")
    if analysis["mode"] == "qc_only" and (contrast_ref or contrast_pairs):
        warnings.append("Contrast settings were requested but are inactive in QC-only mode.")
    if analysis["mode"] == "invalid":
        unresolved.append(f"Analysis mode is unresolved: {analysis['reason_code']}")

    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "harako_version": VERSION,
        "plan_id": "0" * 64,
        "created_at_utc": created_at_utc or utc_now(),
        "input_root": str(root),
        "output_root": str(output),
        "project_name": project_name,
        "library_protocol": library_protocol,
        "samples": normalized_rows,
        "reference": reference,
        "analysis_plan": analysis,
        "contrasts": contrasts,
        "enrichment": enrichment,
        "resources": {"threads": int(threads), "execution_engine": "real"},
        "requested_options": {
            "contrast_mode": contrast_mode,
            "contrast_ref": contrast_ref,
            "contrast_pairs": contrast_pairs or [],
            "enrichment": bool(enable_enrichment),
        },
        "warnings": sorted(set(warnings)),
        "unresolved": sorted(set(unresolved)),
        "approval_required": True,
        "approval_hash": "0" * 64,
    }
    plan["plan_id"] = plan_id_for(plan)
    plan["approval_hash"] = approval_hash_for(plan)
    return plan


def load_plan(path: Path) -> dict[str, Any]:
    return load_document(path)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in FORBIDDEN_PLAN_KEYS or _contains_forbidden_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _rows_from_plan(plan: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {key: str(row.get(key) or "") for key in SAMPLE_COLUMNS}
        for row in plan.get("samples") or []
        if isinstance(row, dict)
    ]


def validate_plan_payload(plan: dict[str, Any]) -> dict[str, Any]:
    errors = schema_errors(plan)
    warnings = list(plan.get("warnings") or []) if isinstance(plan.get("warnings"), list) else []
    unresolved = list(plan.get("unresolved") or []) if isinstance(plan.get("unresolved"), list) else []
    if _contains_forbidden_key(plan):
        errors.append("Plans may not contain commands, scripts, shell strings, or argv fields.")
    computed_plan_id = plan_id_for(plan)
    computed_approval = approval_hash_for(plan)
    if plan.get("plan_id") != computed_plan_id:
        errors.append("plan_id does not match the execution-relevant plan payload.")
    if plan.get("approval_hash") != computed_approval:
        errors.append("approval_hash does not match the execution-relevant plan payload.")
    if plan.get("harako_version") != VERSION:
        version_message = (
            f"Plan Harako version {plan.get('harako_version')} does not match runtime {VERSION}."
        )
        if "library_protocol" not in plan:
            warnings.append(version_message)
        else:
            errors.append(version_message)

    root = Path(str(plan.get("input_root") or ""))
    rows = _rows_from_plan(plan)
    row_errors, row_warnings, row_unresolved, normalized = validate_sample_rows(
        rows, root, allow_missing_conditions=True
    ) if rows and str(root) else (["Plan has no samples or input_root."], [], [], [])
    errors.extend(row_errors)
    warnings.extend(row_warnings)
    unresolved.extend(row_unresolved)
    analysis = plan.get("analysis_plan") if isinstance(plan.get("analysis_plan"), dict) else {}
    if normalized and analysis:
        try:
            assert_analysis_plan_consistent(analysis, normalized)
        except AnalysisPlanError as exc:
            errors.append(str(exc))

    reference = plan.get("reference") if isinstance(plan.get("reference"), dict) else {}
    if reference:
        try:
            manifest_path = Path(str(reference["manifest_path"]))
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            validate_builtin_manifest(manifest)
            canonical, release, _ = get_release_entry(
                manifest, str(reference["requested_preset"]), str(reference["release"])
            )
            if canonical != reference.get("canonical_preset") or release != reference.get("release"):
                errors.append("Reference identity does not match the pinned manifest entry.")
            metadata = (manifest.get("preset_metadata") or {}).get(canonical, {})
            if reference.get("assembly") != metadata.get("assembly"):
                errors.append("Reference assembly does not match the manifest metadata.")
            cache = resolve_existing_cache_paths(
                manifest,
                Path(str(reference["cache_dir"])),
                str(reference["requested_preset"]),
                str(reference["release"]),
            )
            if not cache or not cache.get("verified"):
                unresolved.append("Selected reference files are absent or not checksum-verified.")
            else:
                paths = cache["paths"]
                expected = {
                    "transcripts_fasta": str(paths["transcripts_fasta_url"]),
                    "genome_fasta": str(paths["genome_fasta_url"]),
                    "gtf": str(paths["gtf_url"]),
                }
                if reference.get("expected_paths") != expected:
                    errors.append("Reference paths do not match the checksum-verified cache.")
                expected_provenance = build_reference_provenance(
                    manifest,
                    str(reference["requested_preset"]),
                    str(reference["release"]),
                    paths=expected,
                    checksum_verified=True,
                    cache_source=str(cache["cache_source"]),
                )
                if reference.get("provenance") != expected_provenance or not reference.get("checksum_verified"):
                    errors.append("Reference verification state changed; regenerate and approve the plan.")
        except (KeyError, OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"Reference validation failed: {exc}")

    resources = plan.get("resources") if isinstance(plan.get("resources"), dict) else {}
    if "library_protocol" not in plan:
        warnings.append(
            "This agent plan predates explicit library protocol selection."
        )
        unresolved.append(
            "Regenerate the plan with an explicit library_protocol before dry run or execution."
        )
    else:
        try:
            resolve_library_protocol(plan.get("library_protocol"))
        except ValueError as exc:
            errors.append(str(exc))
    if resources.get("execution_engine") != "real":
        errors.append("Agent plans must use the existing real Harako execution engine.")
    if not isinstance(resources.get("threads"), int) or resources.get("threads", 0) < 1:
        errors.append("threads must be a positive integer.")
    output_value = str(plan.get("output_root") or "")
    output = Path(output_value) if output_value else None
    if output is None or output.resolve() == Path(output.anchor or os.sep):
        errors.append("output_root must not be empty or a filesystem root.")
    elif output.exists() and not output.is_dir():
        errors.append(f"output_root is not a directory: {output}")
    elif not output.exists() and not output.parent.exists():
        errors.append(f"output_root parent does not exist: {output.parent}")
    elif not os.access(output if output.exists() else output.parent, os.W_OK):
        errors.append(f"output_root is not writable: {output}")

    mode = analysis.get("mode")
    contrasts = plan.get("contrasts") if isinstance(plan.get("contrasts"), dict) else {}
    enrichment = plan.get("enrichment") if isinstance(plan.get("enrichment"), dict) else {}
    if mode == "qc_only":
        if contrasts.get("active") or contrasts.get("pairs"):
            errors.append("QC-only plans may not contain active inferential contrasts.")
        if enrichment.get("enabled"):
            errors.append("QC-only plans may not enable enrichment.")
    if mode == "differential" and not contrasts.get("active"):
        unresolved.append("Differential mode requires a valid active contrast.")

    unresolved = sorted(set(str(item) for item in unresolved if str(item)))
    errors = sorted(set(errors))
    valid = not errors
    executable = valid and not unresolved and bool(analysis.get("structurally_valid"))
    reason_code = analysis.get("reason_code") if executable else ("unresolved" if not errors else "invalid_plan")
    return response(
        {
            "valid": valid,
            "executable": executable,
            "analysis_mode": mode,
            "reason_code": reason_code,
            "condition_counts": dict(analysis.get("condition_counts") or {}),
            "plan_id": plan.get("plan_id") if isinstance(plan.get("plan_id"), str) else None,
            "approval_hash": plan.get("approval_hash") if isinstance(plan.get("approval_hash"), str) else None,
            "warnings": sorted(set(warnings)),
            "errors": errors,
            "unresolved": unresolved,
        }
    )


