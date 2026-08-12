"""Agent-neutral planning, execution, and run-inspection interfaces."""

from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

import yaml

from .agent_contracts import (
    AGENT_INTERFACE_VERSION,
    AGENT_SCHEMA_VERSION,
    AgentInterfaceError,
    approval_hash_for,
    load_document,
    plan_id_for,
    response,
    schema_errors,
    utc_now,
    write_document,
)
from .analysis_eligibility import (
    AnalysisPlanError,
    assert_analysis_plan_consistent,
    evaluate_analysis_eligibility,
)
from .reference_presets import (
    build_reference_provenance,
    get_release_entry,
    resolve_existing_cache_paths,
    validate_builtin_manifest,
)
from .ui import scan as scan_utils
from .ui.run import write_frozen_run_config
from .version import VERSION


SCHEMA_VERSION = AGENT_SCHEMA_VERSION
SAMPLE_COLUMNS = ("sample", "condition", "fastq1", "fastq2")
SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
FORBIDDEN_PLAN_KEYS = {"command", "commands", "shell", "argv", "script", "executable_path"}


def canonical_json(payload: Any) -> str:
    from .agent_contracts import canonical_json as _canonical_json

    return _canonical_json(payload)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extension(name: str) -> str:
    lower = name.lower()
    for extension in scan_utils.FASTQ_EXTS:
        if lower.endswith(extension):
            return name[-len(extension) :]
    return Path(name).suffix


def _read_direction(path_value: str) -> str:
    side = scan_utils.read_side(path_value)
    if side == "1":
        return "R1"
    if side == "2":
        return "R2"
    return "single-end"


def inspect_input(input_root: Path) -> dict[str, Any]:
    """Inspect names and filesystem metadata without opening FASTQ content."""
    root = Path(input_root).expanduser().resolve()
    if not root.is_dir():
        raise AgentInterfaceError(f"Input directory does not exist: {root}")
    files = scan_utils.scan_fastq(root)
    relative = [scan_utils.rel(path, root) for path in files]
    available = set(relative)
    warnings: list[str] = []
    unresolved: list[str] = []
    items: list[dict[str, Any]] = []
    paired_keys: set[str] = set()
    single_count = 0
    ambiguous_count = 0

    for path, rel_path in zip(files, relative):
        side = scan_utils.read_side(rel_path)
        matches = sorted(candidate for candidate in scan_utils.infer_pair_candidates(rel_path) if candidate in available)
        if len(matches) > 1:
            status = "ambiguous"
            ambiguous_count += 1
            message = f"Ambiguous mate candidates for {rel_path}: {', '.join(matches)}"
            warnings.append(message)
            unresolved.append(message)
        elif len(matches) == 1:
            status = "paired"
            paired_keys.add(scan_utils.sample_base(rel_path))
        elif side == "2":
            status = "unresolved"
            message = f"R2 file has no candidate R1 mate: {rel_path}"
            warnings.append(message)
            unresolved.append(message)
        elif side == "1":
            status = "single-end"
            single_count += 1
            warnings.append(f"No R2 mate found for {rel_path}; proposed as single-end and requires review.")
        else:
            status = "single-end"
            single_count += 1
        items.append(
            {
                "path": rel_path,
                "name": path.name,
                "extension": _extension(path.name),
                "size_bytes": int(path.stat().st_size),
                "read_direction": _read_direction(rel_path),
                "sample_id_suggestion": scan_utils.sample_base(rel_path),
                "pairing_key": scan_utils.sample_base(rel_path),
                "candidate_mate": matches[0] if len(matches) == 1 else None,
                "candidate_mates": matches,
                "ambiguity_status": status,
            }
        )

    sample_counts = Counter(item["sample_id_suggestion"] for item in items if item["read_direction"] == "single-end")
    duplicate_candidates = sorted(sample for sample, count in sample_counts.items() if count > 1)
    for sample in duplicate_candidates:
        message = f"Duplicate single-end sample-ID candidate: {sample}"
        warnings.append(message)
        unresolved.append(message)

    ignored = sorted(
        scan_utils.rel(path, root)
        for path in root.rglob("*")
        if path.is_file()
        and "fastq" in path.name.lower()
        and not path.name.lower().endswith(scan_utils.FASTQ_EXTS)
    )
    if ignored:
        warnings.append("Ignored files with unsupported FASTQ-like extensions: " + ", ".join(ignored))
    if not items:
        warnings.append("No supported FASTQ files found.")

    return response(
        {
            "input_root": str(root),
            "fastq_files": items,
            "summary": {
                "total_fastq_count": len(items),
                "paired_candidates": len(paired_keys),
                "single_end_candidates": single_count,
                "ambiguous_files": ambiguous_count,
                "duplicate_candidates": duplicate_candidates,
            },
            "warnings": sorted(set(warnings)),
            "unresolved": sorted(set(unresolved)),
        }
    )


def _condition_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    mapping: dict[str, str] = {}
    with Path(path).expanduser().resolve().open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != ["sample", "condition"]:
            raise AgentInterfaceError("Condition map header must be: sample<TAB>condition")
        for line_number, row in enumerate(reader, start=2):
            sample = (row.get("sample") or "").strip()
            condition = (row.get("condition") or "").strip()
            if not sample or not condition:
                raise AgentInterfaceError(f"Condition map row {line_number} has a blank value.")
            if sample in mapping and mapping[sample] != condition:
                raise AgentInterfaceError(
                    f"Conflicting condition assignments for {sample}: {mapping[sample]} and {condition}"
                )
            mapping[sample] = condition
    return mapping


def load_inspection(path: Path) -> dict[str, Any]:
    payload = load_document(path)
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("fastq_files"), list):
        raise AgentInterfaceError("Inspection document is not a Harako input inspection v1.")
    if not payload.get("input_root"):
        raise AgentInterfaceError("Inspection document is missing input_root.")
    return payload


def propose_samples_from_inspection(
    inspection: dict[str, Any], condition_map: Path | None = None
) -> dict[str, Any]:
    root = Path(str(inspection["input_root"])).expanduser().resolve()
    items = sorted(inspection.get("fastq_files") or [], key=lambda item: str(item.get("path") or ""))
    by_path = {str(item.get("path")): item for item in items}
    ambiguous_paths = {
        str(path)
        for item in items
        if item.get("ambiguity_status") == "ambiguous"
        for path in [item.get("path"), *(item.get("candidate_mates") or [])]
        if path
    }
    consumed: set[str] = set()
    rows: list[dict[str, str]] = []
    unresolved = list(inspection.get("unresolved") or [])

    for item in items:
        rel_path = str(item.get("path") or "")
        if not rel_path or rel_path in consumed or rel_path in ambiguous_paths:
            continue
        direction = item.get("read_direction")
        status = item.get("ambiguity_status")
        if status in {"ambiguous", "unresolved"}:
            continue
        if direction == "R2":
            continue
        fastq2 = ""
        pairing_status = "single-end"
        if direction == "R1" and item.get("candidate_mate"):
            mate = item.get("candidate_mate")
            if mate not in by_path or by_path[mate].get("read_direction") != "R2":
                unresolved.append(f"Unresolved R1/R2 pairing for {rel_path}")
                continue
            fastq2 = str(mate)
            pairing_status = "paired"
            consumed.add(fastq2)
        consumed.add(rel_path)
        rows.append(
            {
                "sample": str(item.get("sample_id_suggestion") or ""),
                "condition": "",
                "fastq1": rel_path,
                "fastq2": fastq2,
                "pairing_status": pairing_status,
            }
        )

    duplicates = sorted(sample for sample, count in Counter(row["sample"] for row in rows).items() if count > 1)
    if duplicates:
        raise AgentInterfaceError("Duplicate proposed sample identifiers: " + ", ".join(duplicates))
    mapping = _condition_map(condition_map)
    unknown = sorted(set(mapping) - {row["sample"] for row in rows})
    if unknown:
        raise AgentInterfaceError("Condition map contains unknown samples: " + ", ".join(unknown))
    for row in rows:
        row["condition"] = mapping.get(row["sample"], "")
    missing = [f"Missing explicit condition for sample {row['sample']}" for row in rows if not row["condition"]]
    return response(
        {
            "input_root": str(root),
            "samples": rows,
            "warnings": sorted(set(inspection.get("warnings") or [])),
            "unresolved": sorted(set(unresolved + missing)),
            "conditions_inferred": False,
        }
    )


def propose_samples(input_root: Path, condition_map: Path | None = None) -> dict[str, Any]:
    """Compatibility helper for callers that have not persisted inspection JSON."""
    return propose_samples_from_inspection(inspect_input(input_root), condition_map)


def write_sample_table(path: Path, rows: list[dict[str, str]], *, overwrite: bool = False) -> None:
    destination = Path(path).expanduser().resolve()
    if destination.exists() and not overwrite:
        raise AgentInterfaceError(f"Output already exists; use --force: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SAMPLE_COLUMNS), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in SAMPLE_COLUMNS} for row in rows)


def read_sample_table(path: Path) -> list[dict[str, str]]:
    table = Path(path).expanduser().resolve()
    if not table.is_file():
        raise AgentInterfaceError(f"Sample table does not exist: {table}")
    with table.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        if not set(SAMPLE_COLUMNS).issubset(fields):
            raise AgentInterfaceError("Sample table requires sample, condition, fastq1, and fastq2 columns.")
        return [{key: (row.get(key) or "").strip() for key in SAMPLE_COLUMNS} for row in reader]


def _resolve_under_root(value: str, input_root: Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else input_root / path).resolve()


def _plan_path(path: Path, input_root: Path) -> str:
    try:
        return path.relative_to(input_root).as_posix()
    except ValueError:
        return str(path)


def validate_sample_rows(
    rows: list[dict[str, str]], input_root: Path, *, allow_missing_conditions: bool = False
) -> tuple[list[str], list[str], list[str], list[dict[str, str]]]:
    errors: list[str] = []
    warnings: list[str] = []
    unresolved: list[str] = []
    normalized: list[dict[str, str]] = []
    seen_samples: set[str] = set()
    seen_fastq: set[str] = set()
    for index, row in enumerate(rows, start=2):
        sample = row.get("sample", "").strip()
        condition = row.get("condition", "").strip()
        fq1_text = row.get("fastq1", "").strip()
        fq2_text = row.get("fastq2", "").strip()
        if not sample or not SAMPLE_ID_RE.fullmatch(sample):
            errors.append(f"Sample table row {index}: invalid or missing sample identifier '{sample}'.")
        elif sample in seen_samples:
            errors.append(f"Duplicate sample identifier: {sample}")
        seen_samples.add(sample)
        if not condition:
            message = f"Missing condition for sample {sample or '(blank)'}"
            (unresolved if allow_missing_conditions else errors).append(message)
        if not fq1_text:
            errors.append(f"Sample table row {index}: missing fastq1 for {sample or '(blank)' }.")
            continue
        fq1 = _resolve_under_root(fq1_text, input_root)
        fq2 = _resolve_under_root(fq2_text, input_root) if fq2_text else None
        for label, path in (("fastq1", fq1), ("fastq2", fq2)):
            if path is None:
                continue
            if not path.is_file():
                errors.append(f"Missing {label} for {sample}: {path}")
            if not path.name.lower().endswith(scan_utils.FASTQ_EXTS):
                errors.append(f"Unexpected FASTQ extension for {sample}: {path}")
            if str(path) in seen_fastq:
                errors.append(f"FASTQ path is assigned more than once: {path}")
            seen_fastq.add(str(path))
        if scan_utils.read_side(str(fq1)) == "2":
            errors.append(f"fastq1 is labeled as R2 for {sample}: {fq1.name}")
        pairing_status = "single-end"
        if fq2:
            pairing_status = "paired"
            if scan_utils.read_side(str(fq2)) != "2":
                errors.append(f"fastq2 is not labeled as R2 for {sample}: {fq2.name}")
            if scan_utils.sample_base(str(fq1)) != scan_utils.sample_base(str(fq2)):
                errors.append(f"FASTQ pair sample hints disagree for {sample}.")
        normalized.append(
            {
                "sample": sample,
                "condition": condition,
                "fastq1": _plan_path(fq1, input_root),
                "fastq2": _plan_path(fq2, input_root) if fq2 else "",
                "pairing_status": pairing_status,
            }
        )
    return sorted(set(errors)), sorted(set(warnings)), sorted(set(unresolved)), normalized


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
    rows = read_sample_table(table)
    errors, warnings, unresolved, normalized_rows = validate_sample_rows(rows, root, allow_missing_conditions=True)
    if errors:
        raise AgentInterfaceError("; ".join(errors))
    analysis = _analysis_plan(normalized_rows)

    manifest_path = (ref_manifest or Path(__file__).resolve().parents[1] / "workflow" / "ref_manifest.yaml").resolve()
    cache_dir = (ref_cache_dir or output / "refs_cache").resolve()
    from .cli import _resolve_reference_cfg

    resolved_cfg = _resolve_reference_cfg(
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
        errors.append(f"Plan Harako version {plan.get('harako_version')} does not match runtime {VERSION}.")

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


def _materialize_samples(plan: dict[str, Any], destination: Path) -> Path:
    root = Path(plan["input_root"])
    rows = []
    for row in plan["samples"]:
        rows.append(
            {
                "sample": row["sample"],
                "condition": row["condition"],
                "fastq1": str(_resolve_under_root(row["fastq1"], root)),
                "fastq2": str(_resolve_under_root(row["fastq2"], root)) if row.get("fastq2") else "",
            }
        )
    write_sample_table(destination, rows, overwrite=True)
    return destination


def _config_from_plan(plan: dict[str, Any], output_dir: Path, sample_table: Path) -> dict[str, Any]:
    reference = plan["reference"]
    contrasts = plan["contrasts"]
    config = {
        "project_name": plan["project_name"],
        "engine": plan["resources"]["execution_engine"],
        "input": plan["input_root"],
        "output": str(output_dir),
        "sample_table": str(sample_table),
        "species": reference["species"],
        "ref_preset": reference["canonical_preset"],
        "ref_release": reference["release"],
        "ref_manifest": reference["manifest_path"],
        "ref_cache_dir": reference["cache_dir"],
        "ref": {reference["species"]: reference["expected_paths"]},
        "reference_provenance": reference["provenance"],
        "analysis_plan": plan["analysis_plan"],
        "threads": plan["resources"]["threads"],
        "enrichment": {"enable": bool(plan["enrichment"]["enabled"])},
    }
    if contrasts.get("active"):
        config["contrast_mode"] = contrasts["mode"]
        if contrasts.get("reference"):
            config["contrast_ref"] = contrasts["reference"]
        if contrasts.get("mode") == "select":
            config["contrast_pairs"] = contrasts["pairs"]
    return config


def execute_existing_run(config_path: Path, plan: dict[str, Any], run_dir: Path) -> int:
    from .cli import _run_impl

    try:
        with contextlib.redirect_stdout(sys.stderr):
            return int(
                _run_impl(
                    config=str(config_path), input_dir=plan["input_root"], output_dir=str(run_dir), align="none",
                    engine="real", threads=str(plan["resources"]["threads"]), run_id="", no_validate=False,
                    resume=False, force=True, rerun_incomplete=False, keep_going=False, printshellcmds=False,
                    reason=False, quiet_reason=False, latency_wait=60, dry_run=False, forceall=False,
                    forcerun="", use_conda=False, output_stream=sys.stderr,
                )
            )
    except BaseException as exc:
        exit_code = getattr(exc, "exit_code", None)
        if exit_code is None:
            raise
        return int(exit_code)


def dry_run_plan(
    plan: dict[str, Any], *, runner: Callable[[Path, dict[str, Any], Path], tuple[int, str]] | None = None
) -> dict[str, Any]:
    validation = validate_plan_payload(plan)
    if not validation["valid"] or not validation["executable"]:
        raise AgentInterfaceError("Plan is not executable: " + "; ".join(validation["errors"] + validation["unresolved"]))

    def default_runner(config_path: Path, envelope: dict[str, Any], output_dir: Path) -> tuple[int, str]:
        from .cli import _run_impl

        log_path = output_dir.parent / "snakemake-dry-run.log"
        with log_path.open("w+", encoding="utf-8") as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                code = int(
                    _run_impl(
                        config=str(config_path), input_dir=envelope["input_root"], output_dir=str(output_dir), align="none",
                        engine="real", threads=str(envelope["resources"]["threads"]), run_id="", no_validate=True,
                        resume=False, force=True, rerun_incomplete=False, keep_going=False, printshellcmds=False,
                        reason=False, quiet_reason=True, latency_wait=60, dry_run=True, forceall=False,
                        forcerun="", use_conda=False, output_stream=stream,
                    )
                )
            except BaseException as exc:
                code = int(getattr(exc, "exit_code", 4))
            stream.seek(0)
            return code, stream.read()

    with tempfile.TemporaryDirectory(prefix="harako-agent-dry-run-") as temp:
        planning = Path(temp)
        sample_table = _materialize_samples(plan, planning / "samples.tsv")
        config_path = planning / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(_config_from_plan(plan, planning / "dry-run-output", sample_table), sort_keys=False),
            encoding="utf-8",
        )
        code, output = (runner or default_runner)(config_path, plan, planning / "dry-run-output")
    rules = sorted(set(re.findall(r"(?m)^rule\s+([A-Za-z0-9_]+):", output)))
    summary_lines = [line.strip() for line in output.splitlines() if re.search(r"\bjobs?\b|^total\b", line, re.I)]
    return response(
        {
            "valid": code == 0,
            "executable": True,
            "plan_id": plan["plan_id"],
            "approval_hash": plan["approval_hash"],
            "dry_run_satisfies_approval": False,
            "exit_code": code,
            "planned_rules": rules,
            "job_summary": summary_lines[-20:],
        }
    )


def execute_plan(
    plan: dict[str, Any], *, approval: str | None,
    executor: Callable[[Path, dict[str, Any], Path], int] = execute_existing_run,
) -> dict[str, Any]:
    if approval is None:
        raise AgentInterfaceError("Execution requires --approve with the exact approval_hash.")
    recomputed = approval_hash_for(plan)
    if approval != plan.get("approval_hash") or approval != recomputed:
        raise AgentInterfaceError("Approval hash does not match the current plan; nothing was executed.")
    validation = validate_plan_payload(plan)
    if not validation["valid"] or not validation["executable"]:
        raise AgentInterfaceError("Plan is not executable: " + "; ".join(validation["errors"] + validation["unresolved"]))
    output_root = Path(plan["output_root"])
    run_dir = output_root / "data_out" / f"{plan['project_name']}_{plan['plan_id'][:12]}"
    if run_dir.exists():
        raise AgentInterfaceError(f"Run directory already exists; resume through the ordinary Harako interface: {run_dir}")
    staged_table = output_root / ".agent_planning" / plan["plan_id"] / "samples.tsv"
    _materialize_samples(plan, staged_table)
    config = _config_from_plan(plan, run_dir, staged_table)
    config_path = write_frozen_run_config(run_dir, config, sample_table_source=staged_table)
    staged_table.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        staged_table.parent.rmdir()
        staged_table.parent.parent.rmdir()
    run_meta = run_dir / "run"
    write_document(run_meta / "approved-agent-plan.yaml", plan, force=True)
    approval_record = response(
        {
            "plan_id": plan["plan_id"],
            "approval_hash": approval,
            "approved_at_utc": utc_now(),
            "plan_schema_version": plan["schema_version"],
            "agent_interface_version": AGENT_INTERFACE_VERSION,
        }
    )
    (run_meta / "agent_approval.json").write_text(json.dumps(approval_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status_path = run_meta / "agent_status.json"
    status_path.write_text(
        json.dumps(response({"state": "running", "pid": os.getpid(), "started_at_utc": utc_now()}), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        code = int(executor(config_path, plan, run_dir))
    except Exception as exc:
        status_path.write_text(
            json.dumps(response({"state": "failed", "failed_stage": None, "message": str(exc)}), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    state = "completed" if code == 0 else "failed"
    status_path.write_text(
        json.dumps(response({"state": state, "exit_code": code, "finished_at_utc": utc_now()}), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return response(
        {
            "plan_id": plan["plan_id"], "approval_hash": approval, "run_dir": str(run_dir),
            "state": state, "exit_code": code,
        }
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_run_config(run_dir: Path) -> dict[str, Any]:
    return _load_yaml_mapping(run_dir / "run" / "config_resolved.yaml")


def _run_dir(path: Path) -> Path:
    run = Path(path).expanduser().resolve()
    if not run.is_dir() or not (run / "run" / "config_resolved.yaml").is_file():
        raise AgentInterfaceError(f"Harako run was not found: {run}")
    return run


def _relative_files(run: Path, patterns: list[str]) -> list[str]:
    found: set[str] = set()
    for pattern in patterns:
        for path in run.glob(pattern):
            if path.is_file():
                try:
                    found.add(path.resolve().relative_to(run).as_posix())
                except ValueError:
                    continue
    return sorted(found)


def _pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    process_query_limited_information = 0x1000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    wait_failed = 0xFFFFFFFF
    error_access_denied = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(synchronize | process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied
    try:
        result = wait_for_single_object(handle, 0)
        if result == wait_timeout:
            return True
        if result == wait_object_0:
            return False
        if result == wait_failed and ctypes.get_last_error() == error_access_denied:
            return True
        return False
    finally:
        close_handle(handle)


def _pid_alive(pid: Any) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        if pid > 0xFFFFFFFF:
            return False
        # os.kill(pid, 0) is unsafe here: signal zero collides with Windows console-control behavior.
        return _pid_alive_windows(pid)
    return _pid_alive_posix(pid)


def run_status(run_dir: Path) -> dict[str, Any]:
    run = _run_dir(run_dir)
    config = _load_run_config(run)
    manifest = _load_json(run / "run" / "manifest.json")
    de_status = _load_json(run / "deseq2" / "status.json")
    agent_status = _load_json(run / "run" / "agent_status.json")
    analysis = config.get("analysis_plan") if isinstance(config.get("analysis_plan"), dict) else {}
    mode = de_status.get("mode") or analysis.get("mode")
    report = (run / "report" / "report.html").is_file()
    state = "planned"
    if agent_status.get("state") == "failed":
        state = "failed"
    elif agent_status.get("state") == "running":
        state = "running" if _pid_alive(agent_status.get("pid")) else "interrupted"
    elif agent_status.get("state") == "completed":
        state = "completed" if de_status else "interrupted"
    elif de_status and report:
        state = "completed"
    elif manifest:
        state = "running"
    completed_stages: list[str] = []
    stage_checks = {
        "fastp": bool(_relative_files(run, ["fastp/*.json", "fastp/*.html"])),
        "salmon": bool(_relative_files(run, ["salmon/*/quant.sf"])),
        "tximport": (run / "tximport" / "txi.tsv").is_file(),
        "deseq2": bool(de_status),
        "report": report,
    }
    completed_stages.extend(stage for stage, complete in stage_checks.items() if complete)
    logs = _relative_files(run, ["logs/**/*.log", "run/snakemake*.log", "run/snakemake_*.txt"])
    de_available = bool(mode == "differential" and de_status.get("differential_results_available"))
    enrichment_available = bool(
        mode == "differential" and de_status.get("enrichment_allowed") and _relative_files(run, ["results/enrichment/**/status.json"])
    )
    next_steps = {
        "planned": "Execute the approved plan.",
        "running": "Wait and inspect status again.",
        "completed": "Inspect artifacts or create a post-analysis workspace.",
        "failed": "Inspect the reported failed stage and logs.",
        "interrupted": "Inspect logs and resume through the ordinary Harako execution path.",
        "unknown": "Inspect the frozen run configuration and logs.",
    }
    return response(
        {
            "run_id": manifest.get("run_id"),
            "project_name": config.get("project_name"),
            "state": state,
            "analysis_mode": mode,
            "reason_code": analysis.get("reason_code"),
            "condition_counts": dict(analysis.get("condition_counts") or {}),
            "completed_workflow_stages": completed_stages,
            "failed_stage": agent_status.get("failed_stage"),
            "report_available": report,
            "counts_available": (run / "tximport" / "txi.tsv").is_file(),
            "tpm_available": (run / "tximport" / "tpm.tsv").is_file(),
            "de_results_available": de_available,
            "enrichment_available": enrichment_available,
            "log_paths": logs,
            "actionable_next_step": next_steps.get(state, next_steps["unknown"]),
        }
    )


def _artifact(run: Path, kind: str, relative: str, mode: str | None, description: str, *, applicable: bool = True) -> dict[str, Any]:
    path = run / Path(relative)
    exists = path.is_file() and applicable
    return {
        "artifact_type": kind,
        "relative_path": Path(relative).as_posix(),
        "exists": exists,
        "size_bytes": int(path.stat().st_size) if exists else None,
        "generated": exists,
        "applicable": applicable,
        "analysis_mode": mode,
        "description": description,
    }


def artifact_inventory(run_dir: Path) -> dict[str, Any]:
    run = _run_dir(run_dir)
    status = run_status(run)
    mode = status.get("analysis_mode")
    differential = mode == "differential"
    items = [
        _artifact(run, "tximport_counts", "tximport/txi.tsv", mode, "Gene-level counts used by DESeq2."),
        _artifact(run, "gene_level_tpm", "tximport/tpm.tsv", mode, "Gene-level TPM abundance measure; not DESeq2 input."),
        _artifact(run, "normalized_counts", "deseq2/normalized_counts.tsv", mode, "DESeq2 normalized counts.", applicable=differential),
        _artifact(run, "deseq2_status", "deseq2/status.json", mode, "Scientific source of truth for DESeq2 availability."),
        _artifact(run, "deseq2_results", "deseq2/results.tsv", mode, "Inferential differential-expression results.", applicable=differential and status["de_results_available"]),
        _artifact(run, "pca", "deseq2/pca.png", mode, "PCA quality-control plot."),
        _artifact(run, "sample_distance", "deseq2/sample_distance_heatmap.png", mode, "Sample-distance quality-control plot."),
        _artifact(run, "ma_plot", "deseq2/ma_plot.png", mode, "MA plot.", applicable=differential),
        _artifact(run, "volcano_plot", "deseq2/volcano.png", mode, "Volcano plot.", applicable=differential),
        _artifact(run, "html_report", "report/report.html", mode, "Self-contained Harako HTML report."),
        _artifact(run, "frozen_config", "run/config_resolved.yaml", mode, "Immutable effective Harako configuration."),
        _artifact(run, "sample_table", "run/metadata/samples.tsv", mode, "Frozen sample table."),
        _artifact(run, "run_manifest", "run/manifest.json", mode, "Harako run identity and provenance manifest."),
        _artifact(run, "versions", "run/versions.tsv", mode, "Software and reference version record."),
        _artifact(run, "approved_agent_plan", "run/approved-agent-plan.yaml", mode, "Canonical approved agent plan."),
    ]
    dynamic_specs = [
        ("fastp_json", "fastp/*.json", "fastp per-sample JSON QC."),
        ("fastp_html", "fastp/*.html", "fastp per-sample HTML QC."),
        ("processed_fastq", "fastp/*.fastq*", "Preprocessed FASTQ generated by fastp."),
        ("salmon_quant", "salmon/*/quant.sf", "Salmon transcript-level quantification."),
        ("enrichment", "results/enrichment/**/status.json", "Enrichment result status."),
        ("log", "logs/**/*.log", "Harako workflow log."),
    ]
    for kind, pattern, description in dynamic_specs:
        applicable = not (kind == "enrichment" and not differential)
        for relative in _relative_files(run, [pattern]):
            items.append(_artifact(run, kind, relative, mode, description, applicable=applicable))
    items.sort(key=lambda item: (item["artifact_type"], item["relative_path"]))
    return response({"run_id": status.get("run_id"), "analysis_mode": mode, "artifacts": items})


def _parse_versions(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return {str(row.get("key")): str(row.get("value")) for row in reader if row.get("key")}


def build_agent_context(run_dir: Path) -> dict[str, Any]:
    run = _run_dir(run_dir)
    config = _load_run_config(run)
    approved_plan = _load_yaml_mapping(run / "run" / "approved-agent-plan.yaml")
    plan_contrasts = approved_plan.get("contrasts")
    if isinstance(plan_contrasts, dict):
        contrasts = plan_contrasts
    else:
        contrasts = {
            "mode": config.get("contrast_mode"),
            "reference": config.get("contrast_ref"),
            "pairs": config.get("contrast_pairs") or [],
        }
    status = run_status(run)
    inventory = artifact_inventory(run)
    rows = []
    table = run / "run" / "metadata" / "samples.tsv"
    if table.is_file():
        rows = [{"sample": row["sample"], "condition": row["condition"]} for row in read_sample_table(table)]
    return response(
        {
            "purpose": "Local agent index; not intended for automatic cloud upload.",
            "run": {
                "run_id": status.get("run_id"),
                "project_name": status.get("project_name"),
                "analysis_mode": status.get("analysis_mode"),
                "reason_code": status.get("reason_code"),
            },
            "samples": rows,
            "contrasts": {
                "mode": contrasts.get("mode"),
                "reference": contrasts.get("reference"),
                "pairs": contrasts.get("pairs") or [],
            },
            "reference_provenance": {
                key: value
                for key, value in dict(config.get("reference_provenance") or {}).items()
                if key not in {"transcripts_fasta", "genome_fasta", "gtf"}
            },
            "tool_versions": _parse_versions(run / "run" / "versions.tsv"),
            "artifacts": inventory["artifacts"],
            "output_schemas": {
                "tximport/txi.tsv": "Gene-level count matrix used for DESeq2 modeling.",
                "tximport/tpm.tsv": "Gene-level TPM abundance matrix; not DESeq2 input.",
                "deseq2/status.json": "Authoritative DESeq2/QC-only availability status.",
            },
            "warnings": [
                "FASTQ contents, credentials, environment variables, and unrestricted tracebacks are excluded.",
                "The minimum replication gate is not a power calculation or proof of biological independence.",
                "Treat frozen Harako outputs as read-only scientific evidence.",
            ],
        }
    )


def init_post_analysis(run_dir: Path, name: str, question: str = "") -> dict[str, Any]:
    run = _run_dir(run_dir)
    analysis_id = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
    if not analysis_id:
        raise AgentInterfaceError("Post-analysis name must contain a letter or number.")
    workspace = run.parent / "post_analysis" / analysis_id
    if workspace.exists():
        raise AgentInterfaceError(f"Post-analysis workspace already exists: {workspace}")
    for directory in ("scripts", "figures", "tables", "reports", "logs", "environment"):
        (workspace / directory).mkdir(parents=True, exist_ok=False)
    status = run_status(run)
    inventory = artifact_inventory(run)
    selected = []
    hashable = {"run_manifest", "frozen_config", "sample_table", "tximport_counts", "gene_level_tpm", "deseq2_status", "deseq2_results"}
    for item in inventory["artifacts"]:
        if not item["exists"] or item["artifact_type"] not in hashable:
            continue
        path = run / item["relative_path"]
        selected.append({**item, "sha256": sha256_file(path) if path.stat().st_size <= 100 * 1024 * 1024 else None})
    created = utc_now()
    source_manifest = response(
        {
            "source_run_id": status.get("run_id"),
            "source_run_relative_path": run.name,
            "harako_version": VERSION,
            "analysis_mode": status.get("analysis_mode"),
            "source_manifest": "run/manifest.json",
            "selected_read_only_artifacts": selected,
        }
    )
    analysis = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": analysis_id,
        "created_at_utc": created,
        "user_question": question,
        "source_run_id": status.get("run_id"),
        "source_analysis_mode": status.get("analysis_mode"),
        "ownership": {
            "harako_outputs": "read-only source evidence",
            "post_analysis_outputs": "agent- or user-generated, not Harako core results",
        },
        "scripts": [],
        "generated_outputs": [],
    }
    (workspace / "input_manifest.json").write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (workspace / "analysis.yaml").write_text(yaml.safe_dump(analysis, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (workspace / "README.md").write_text(
        "# Post-analysis workspace\n\n"
        "This workspace is separate from the immutable Harako core run. Treat all referenced Harako artifacts as read-only. "
        "Scripts and interpretations created here are not Harako-generated scientific outputs.\n",
        encoding="utf-8",
    )
    return response(
        {"analysis_id": analysis_id, "workspace": str(workspace), "source_run_id": status.get("run_id"), "question": question}
    )
