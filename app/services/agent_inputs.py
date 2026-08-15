"""Agent-facing input inspection and explicit sample-table services."""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.agent_contracts import AGENT_SCHEMA_VERSION, AgentInterfaceError, load_document, response
from app.core import fastq as fastq_rules
from app.services import input_files


SCHEMA_VERSION = AGENT_SCHEMA_VERSION
SAMPLE_COLUMNS = ("sample", "condition", "fastq1", "fastq2")
SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

def _extension(name: str) -> str:
    lower = name.lower()
    for extension in fastq_rules.FASTQ_EXTS:
        if lower.endswith(extension):
            return name[-len(extension) :]
    return Path(name).suffix


def _read_direction(path_value: str) -> str:
    side = fastq_rules.read_side(path_value)
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
    files = input_files.scan_fastq(root)
    relative = [fastq_rules.relative_path(path, root) for path in files]
    available = set(relative)
    warnings: list[str] = []
    unresolved: list[str] = []
    items: list[dict[str, Any]] = []
    paired_keys: set[str] = set()
    single_count = 0
    ambiguous_count = 0

    for path, rel_path in zip(files, relative):
        side = fastq_rules.read_side(rel_path)
        matches = sorted(candidate for candidate in fastq_rules.infer_pair_candidates(rel_path) if candidate in available)
        if len(matches) > 1:
            status = "ambiguous"
            ambiguous_count += 1
            message = f"Ambiguous mate candidates for {rel_path}: {', '.join(matches)}"
            warnings.append(message)
            unresolved.append(message)
        elif len(matches) == 1:
            status = "paired"
            paired_keys.add(fastq_rules.sample_base(rel_path))
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
                "sample_id_suggestion": fastq_rules.sample_base(rel_path),
                "pairing_key": fastq_rules.sample_base(rel_path),
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
        fastq_rules.relative_path(path, root)
        for path in root.rglob("*")
        if path.is_file()
        and "fastq" in path.name.lower()
        and not path.name.lower().endswith(fastq_rules.FASTQ_EXTS)
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
            if not path.name.lower().endswith(fastq_rules.FASTQ_EXTS):
                errors.append(f"Unexpected FASTQ extension for {sample}: {path}")
            if str(path) in seen_fastq:
                errors.append(f"FASTQ path is assigned more than once: {path}")
            seen_fastq.add(str(path))
        if fastq_rules.read_side(str(fq1)) == "2":
            errors.append(f"fastq1 is labeled as R2 for {sample}: {fq1.name}")
        pairing_status = "single-end"
        if fq2:
            pairing_status = "paired"
            if fastq_rules.read_side(str(fq2)) != "2":
                errors.append(f"fastq2 is not labeled as R2 for {sample}: {fq2.name}")
            if fastq_rules.sample_base(str(fq1)) != fastq_rules.sample_base(str(fq2)):
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


