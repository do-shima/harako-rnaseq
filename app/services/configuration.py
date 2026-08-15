"""Configuration loading and normalization shared by CLI and agent workflows."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from app.core.analysis import evaluate_analysis_eligibility, resolve_analysis_plan
from app.core.protocol import is_frozen_run_config, resolve_library_protocol
from app.reference_presets import (
    build_reference_provenance,
    resolve_existing_cache_paths,
    resolve_preset_release,
    validate_builtin_manifest,
)


def absolute_path(value: str | None) -> str | None:
    if value is None:
        return None
    return os.path.abspath(os.path.expanduser(value))


def resolve_path(path: str | None, input_dir: str | None, config_dir: str | None) -> str | None:
    if path is None:
        return None
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)
    if input_dir:
        return os.path.abspath(os.path.join(input_dir, expanded))
    if config_dir:
        return os.path.abspath(os.path.join(config_dir, expanded))
    return os.path.abspath(expanded)


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload if isinstance(payload, dict) else {}


def write_yaml(payload: dict[str, Any], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def parse_sample_table(path: str | Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        header = handle.readline().strip().split("\t")
        for line in handle:
            if not line.strip():
                continue
            values = line.rstrip("\n").split("\t")
            rows.append(dict(zip(header, values)))
    return rows


def contrast_levels(sample_rows: list[dict[str, Any]]) -> list[str]:
    levels: list[str] = []
    seen: set[str] = set()
    for row in sample_rows:
        condition = row.get("condition") or ""
        if condition and condition not in seen:
            levels.append(str(condition))
            seen.add(str(condition))
    return levels


def canonical_contrast(left: str, right: str) -> str:
    return f"{left}_vs_{right}"


def resolve_contrasts(config: dict[str, Any], sample_rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligibility = evaluate_analysis_eligibility(sample_rows)
    levels = contrast_levels(sample_rows)
    mode = config.get("contrast_mode")
    legacy = config.get("contrasts") or []
    if not mode:
        mode = "legacy" if legacy else ("ref" if levels else "legacy")
    resolved_pairs: list[tuple[str, str]] = []
    if eligibility.eligible_for_de:
        if mode == "ref":
            reference = config.get("contrast_ref") or (levels[0] if levels else None)
            if reference:
                resolved_pairs.extend((level, reference) for level in levels if level != reference)
        elif mode == "pairwise":
            for left_index in range(len(levels)):
                for right_index in range(left_index + 1, len(levels)):
                    resolved_pairs.append((levels[left_index], levels[right_index]))
        elif mode == "select":
            for pair in config.get("contrast_pairs") or []:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    resolved_pairs.append((pair[0], pair[1]))
        else:
            for item in legacy:
                if "_vs_" in item:
                    left, right = item.split("_vs_", 1)
                    resolved_pairs.append((left, right))
    return {
        "mode": mode,
        "levels": levels,
        "ref": config.get("contrast_ref"),
        "pairs": resolved_pairs,
        "generated": [canonical_contrast(left, right) for left, right in resolved_pairs],
    }


def resolve_fastq_from_config(config: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    fastq = config.get("fastq") or {}
    fastq1 = config.get("fastq1") or {}
    fastq2 = config.get("fastq2") or {}
    if fastq1 or fastq2:
        return fastq1, fastq2
    return fastq, {}


def resolve_reference_config(config: dict[str, Any], config_path: str) -> dict[str, Any]:
    resolved = dict(config)
    preset = resolved.get("ref_preset")
    if not preset:
        return resolved
    reference = resolved.get("ref")
    species = str(resolved.get("species") or "").lower()
    explicit = reference if isinstance(reference, dict) else {}
    if species and isinstance(explicit.get(species), dict):
        explicit = explicit[species]
    if isinstance(explicit, dict) and explicit.get("transcripts_fasta"):
        return resolved

    manifest_path = Path(
        resolved.get("ref_manifest")
        or Path(__file__).resolve().parents[2] / "workflow" / "ref_manifest.yaml"
    )
    if not manifest_path.is_absolute():
        manifest_path = Path(config_path).resolve().parent / manifest_path
    manifest = load_yaml(manifest_path)
    validate_builtin_manifest(manifest)
    requested_release = resolved.get("ref_release", "pinned")
    canonical, release = resolve_preset_release(manifest, preset, requested_release)
    cache_root = Path(resolved.get("ref_cache_dir") or Path(resolved.get("output") or ".") / "refs_cache")
    if not cache_root.is_absolute():
        cache_root = Path(config_path).resolve().parent / cache_root
    cache = resolve_existing_cache_paths(manifest, cache_root, preset, requested_release)
    if cache:
        raw_paths = cache["paths"]
        paths = {
            "transcripts_fasta": str(raw_paths["transcripts_fasta_url"]),
            "genome_fasta": str(raw_paths["genome_fasta_url"]),
            "gtf": str(raw_paths["gtf_url"]),
        }
        verified = bool(cache["verified"])
        cache_source = cache["cache_source"]
    else:
        base = cache_root / canonical / release
        paths = {
            "transcripts_fasta": str(base / "transcripts.fa.gz"),
            "genome_fasta": str(base / "genome.fa.gz"),
            "gtf": str(base / "annotation.gtf.gz"),
        }
        verified = False
        cache_source = "canonical"
    resolved["ref_preset"] = canonical
    resolved["ref_release"] = release
    resolved["ref"] = {species: paths}
    resolved["reference_provenance"] = build_reference_provenance(
        manifest,
        preset,
        requested_release,
        paths=paths,
        checksum_verified=verified,
        cache_source=cache_source,
    )
    return resolved


def resolve_run_config(
    config: dict[str, Any],
    config_path: str,
    final_input: str,
    final_output: str,
    align: str,
    engine: str,
    threads: str,
    use_conda: bool,
) -> dict[str, Any]:
    resolved = dict(config)
    resolved["library_protocol"] = resolve_library_protocol(
        resolved.get("library_protocol"),
        legacy_frozen=is_frozen_run_config(config_path),
    )
    resolved["input"] = absolute_path(final_input) if final_input else ""
    resolved["output"] = absolute_path(final_output) if final_output else ""
    resolved["align"] = align
    if engine:
        resolved["engine"] = engine
    if threads:
        resolved["threads"] = int(threads)
    resolved["use_conda"] = bool(use_conda)
    config_dir = os.path.dirname(absolute_path(config_path)) if config_path else ""
    if "sample_table" in resolved:
        resolved["sample_table"] = resolve_path(resolved["sample_table"], resolved.get("input"), config_dir)
        try:
            rows = parse_sample_table(resolved["sample_table"])
            plan, _ = resolve_analysis_plan(
                resolved.get("analysis_plan"),
                rows,
                legacy_frozen=is_frozen_run_config(config_path),
            )
            resolved["analysis_plan"] = plan
            resolved["contrast_resolved"] = resolve_contrasts(resolved, rows)
            if not plan["eligible_for_de"]:
                enrichment = dict(resolved.get("enrichment") or {})
                if enrichment:
                    enrichment["enable"] = False
                    resolved["enrichment"] = enrichment
        except OSError:
            pass
    return resolve_reference_config(resolved, config_path)
