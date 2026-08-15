"""Neutral configuration and scientific-eligibility validation service."""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.adapters.environment import tool_check_errors
from app.core.analysis import AnalysisEligibility, AnalysisPlanError, assert_analysis_plan_consistent, evaluate_analysis_eligibility
from app.core.fastq import FASTQ_EXTS
from app.core.protocol import LEGACY_UNSPECIFIED, is_frozen_run_config, resolve_library_protocol
from app.reference_presets import ReferencePresetError
from app.services.configuration import (
    absolute_path,
    contrast_levels,
    load_yaml,
    parse_sample_table,
    resolve_fastq_from_config,
    resolve_path,
    resolve_reference_config,
)
from app.services.input_files import scan_fastq


SAMPLE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class ValidationResult:
    config: dict[str, Any]
    input_dir: str | None
    output_dir: str | None
    eligibility: AnalysisEligibility
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _validate_paths(paths: list[str | None], errors: list[str], label: str) -> None:
    for path in paths:
        if path and not os.path.exists(path):
            errors.append(f"Missing {label} file: {path}")


def _check_output_writable(output_dir: str | None, errors: list[str]) -> None:
    if not output_dir:
        return
    try:
        os.makedirs(output_dir, exist_ok=True)
        if os.path.exists(output_dir) and not os.path.isdir(output_dir):
            errors.append(f"Output path is not a directory: {output_dir}")
            return
        test_path = os.path.join(output_dir, ".validate_write_test")
        with open(test_path, "w", encoding="utf-8") as handle:
            handle.write("ok\n")
        os.remove(test_path)
    except Exception as exc:
        errors.append(f"Output directory is not writable: {output_dir} ({exc})")


def _fastq_warnings(paths: list[str], warnings: list[str]) -> None:
    for path in paths:
        if path and not path.lower().endswith(FASTQ_EXTS):
            warnings.append(f"FASTQ file has unexpected extension: {path}")
    counts = Counter(path for path in paths if path)
    duplicates = [path for path, count in counts.items() if count > 1]
    if duplicates:
        warnings.append(f"Duplicate FASTQ paths detected: {', '.join(duplicates)}")


def _sample_name_warnings(samples: list[str], warnings: list[str]) -> None:
    for sample in samples:
        if sample and not SAMPLE_NAME_RE.match(sample):
            warnings.append(
                f"Sample name '{sample}' contains spaces/special chars. "
                "Use letters, numbers, dot, underscore, or dash."
            )


def _validate_contrasts(
    config: dict[str, Any],
    sample_rows: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
    eligibility: AnalysisEligibility,
) -> None:
    levels = contrast_levels(sample_rows)
    if not eligibility.structurally_valid:
        return
    if not eligibility.eligible_for_de:
        warnings.append(
            f"Analysis mode is qc_only ({eligibility.reason_code}); contrasts are "
            "retained as requested settings but are not applied."
        )
        return
    mode = config.get("contrast_mode")
    legacy = config.get("contrasts") or []
    if mode == "legacy" or legacy:
        errors.append(
            "Legacy contrasts are not supported. "
            "Use contrast_mode=ref|pairwise|select with contrast_ref or contrast_pairs."
        )
        return
    if mode == "ref":
        reference = config.get("contrast_ref")
        if not reference:
            errors.append("contrast_ref is required when contrast_mode=ref.")
        elif reference not in levels:
            errors.append(f"contrast_ref '{reference}' not in detected levels {levels}.")
        if len(levels) < 2:
            errors.append("contrast_mode=ref requires at least two condition levels.")
    elif not mode and levels:
        reference = config.get("contrast_ref")
        if reference and reference not in levels:
            errors.append(f"contrast_ref '{reference}' not in detected levels {levels}.")
        if not reference and len(levels) >= 2:
            warnings.append(f"contrast_mode not set; defaulting to ref using {levels[0]}.")
    elif mode == "pairwise":
        if len(levels) < 2:
            errors.append("contrast_mode=pairwise requires at least two condition levels.")
    elif mode == "select":
        pairs = config.get("contrast_pairs") or []
        if not pairs:
            errors.append("contrast_mode=select requires contrast_pairs.")
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                errors.append(f"Invalid contrast pair: {pair} (expected [A, B]).")
                continue
            left, right = pair
            if left == right:
                errors.append(f"Invalid contrast pair: {left}_vs_{right} (A and B must differ).")
            if left not in levels or right not in levels:
                errors.append(f"Invalid contrast pair: {left}_vs_{right} (levels={levels}).")


def validate_configuration(
    config_path: str,
    *,
    input_dir: str | None = None,
    output_dir: str | None = None,
    skip_toolcheck: bool = False,
) -> ValidationResult:
    config = load_yaml(config_path)
    absolute_config_path = absolute_path(config_path)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        candidate = dict(config)
        if output_dir:
            candidate["output"] = absolute_path(output_dir)
        config = resolve_reference_config(candidate, absolute_config_path)
    except (ReferencePresetError, OSError, yaml.YAMLError) as exc:
        errors.append(str(exc))

    config_dir = os.path.dirname(absolute_config_path)
    resolved_input = absolute_path(input_dir) if input_dir else absolute_path(config.get("input"))
    resolved_output = absolute_path(output_dir) if output_dir else absolute_path(config.get("output"))
    try:
        config["library_protocol"] = resolve_library_protocol(
            config.get("library_protocol"),
            legacy_frozen=is_frozen_run_config(absolute_config_path),
        )
        if config["library_protocol"] == LEGACY_UNSPECIFIED:
            warnings.append(
                "This frozen run predates explicit library protocol selection; "
                "historical tximport-to-DESeq2 behavior is preserved. Create a new run for reanalysis."
            )
    except ValueError as exc:
        errors.append(str(exc))

    engine = config.get("engine", "real")
    samples = list(config.get("samples") or [])
    sample_rows: list[dict[str, Any]] = []
    if resolved_input and not scan_fastq(Path(resolved_input)):
        errors.append(
            f"No FASTQ files found under input: {resolved_input}. "
            "Hint: mount FASTQ files under /input (e.g. -v <host>:/input:ro)."
        )

    sample_table = config.get("sample_table")
    if sample_table:
        sample_table = resolve_path(sample_table, resolved_input, config_dir)
        if not os.path.exists(sample_table):
            errors.append(f"Sample table not found: {sample_table}")
        else:
            rows = parse_sample_table(sample_table)
            sample_rows = rows
            samples = [row.get("sample") for row in rows if row.get("sample")]
            if not samples:
                errors.append("Sample table has no samples.")
            fastq1 = [row.get("fastq1") for row in rows]
            fastq2 = [row.get("fastq2") for row in rows]
            for index, row in enumerate(rows, start=2):
                sample_id = row.get("sample")
                if not sample_id:
                    errors.append(f"Sample table row {index}: missing sample value.")
                if not row.get("condition"):
                    errors.append(f"Sample table row {index}: missing condition for sample {sample_id or '(blank)'}")
                if not row.get("fastq1"):
                    errors.append(f"Sample table row {index}: missing fastq1 for sample {sample_id or '(blank)'}")
            resolved_fastq1 = [resolve_path(path, resolved_input, config_dir) for path in fastq1 if path]
            resolved_fastq2 = [resolve_path(path, resolved_input, config_dir) for path in fastq2 if path]
            _validate_paths(resolved_fastq1, errors, "FASTQ")
            if any(fastq2):
                _validate_paths(resolved_fastq2, errors, "FASTQ (R2)")
                if not all(fastq2):
                    warnings.append("Paired-end FASTQ2 missing for some samples.")
            for index, row in enumerate(rows):
                if row.get("fastq2") and not row.get("fastq1"):
                    errors.append(f"Sample {row.get('sample') or index} has FASTQ2 but no FASTQ1.")
            _fastq_warnings(resolved_fastq1 + resolved_fastq2, warnings)
            _sample_name_warnings(samples, warnings)
    else:
        if not samples:
            errors.append("No samples defined in config.")
        conditions = config.get("conditions") or {}
        sample_rows = [{"sample": sample, "condition": conditions.get(sample, "")} for sample in samples]
        if engine == "real":
            missing_conditions = [sample for sample in samples if not conditions.get(sample)]
            if missing_conditions:
                errors.append("Missing condition for sample(s): " + ", ".join(missing_conditions))
        fastq1, fastq2 = resolve_fastq_from_config(config)
        resolved_fastq1: list[str] = []
        resolved_fastq2: list[str] = []
        for sample in samples:
            if sample not in fastq1:
                errors.append(f"Missing FASTQ for sample: {sample}")
            else:
                path = resolve_path(fastq1[sample], resolved_input, config_dir)
                resolved_fastq1.append(path)
                _validate_paths([path], errors, "FASTQ")
            if fastq2 and sample in fastq2:
                path = resolve_path(fastq2[sample], resolved_input, config_dir)
                resolved_fastq2.append(path)
                _validate_paths([path], errors, "FASTQ (R2)")
            elif fastq2:
                warnings.append(f"Missing FASTQ2 for sample: {sample}")
        _fastq_warnings(resolved_fastq1 + resolved_fastq2, warnings)
        _sample_name_warnings(samples, warnings)

    eligibility = evaluate_analysis_eligibility(sample_rows)
    structural_messages = {
        "no_samples": "No samples are available for analysis.",
        "missing_sample": "Sample table contains an empty sample identifier.",
        "missing_condition": "Sample table contains an empty condition.",
        "duplicate_sample": "Sample table contains a duplicate sample identifier.",
    }
    if not eligibility.structurally_valid:
        message = structural_messages.get(eligibility.reason_code)
        if message and message not in errors:
            errors.append(message)
    if config.get("analysis_plan"):
        try:
            assert_analysis_plan_consistent(config["analysis_plan"], sample_rows)
        except AnalysisPlanError as exc:
            errors.append(str(exc))
    _validate_contrasts(config, sample_rows, errors, warnings, eligibility)

    reference = config.get("ref") or {}
    species = (config.get("species") or "").strip().lower()
    species_reference = reference.get(species) if isinstance(reference, dict) and isinstance(reference.get(species), dict) else {}
    preset = config.get("ref_preset")
    if "ref_preset" in config and not preset:
        errors.append("ref_preset is empty. Set ref_preset or provide explicit ref paths.")
    transcripts = resolve_path(reference.get("transcripts_fasta") or species_reference.get("transcripts_fasta"), resolved_input, config_dir)
    genome = resolve_path(reference.get("genome_fasta") or species_reference.get("genome_fasta"), resolved_input, config_dir)
    gtf = resolve_path(reference.get("gtf") or species_reference.get("gtf"), resolved_input, config_dir)
    if preset:
        _validate_paths([path for path in (transcripts, genome, gtf) if path], errors, "reference")
        provenance = config.get("reference_provenance") or {}
        if not provenance.get("checksum_verified"):
            warnings.append(f"Built-in reference {preset}/{config.get('ref_release')} is not checksum-verified.")
    else:
        if not (transcripts and not (genome or gtf)):
            missing = [name for name, value in (("transcripts_fasta", transcripts), ("genome_fasta", genome), ("gtf", gtf)) if not value]
            if missing:
                errors.append("Missing reference field(s): " + ", ".join(missing))
        if engine == "real" and not transcripts:
            errors.append("transcripts_fasta is required for engine=real.")
        _validate_paths([path for path in (transcripts, genome, gtf) if path], errors, "reference")
        if any(error.startswith("Missing reference file:") for error in errors):
            errors.append(
                "Hint: place reference files under /input (e.g. /input/refs/...) "
                "or set ref paths relative to --input."
            )

    enrichment = config.get("enrichment") or {}
    if enrichment.get("enable"):
        methods = [str(method).upper() for method in enrichment.get("methods") or ["ORA", "GSEA"]]
        invalid = [method for method in methods if method not in ("ORA", "GSEA")]
        if invalid:
            errors.append(f"Invalid enrichment methods: {', '.join(invalid)} (allowed: ORA, GSEA)")
        if "GSEA" in methods and enrichment.get("rank_metric", "stat") != "stat":
            warnings.append("GSEA rank_metric should be 'stat' for DESeq2 results.")
        if config.get("species", "mouse") not in ("human", "mouse", "rat"):
            warnings.append("Enrichment enabled for unsupported species; orgdb may be missing and runs will be skipped.")
        if not eligibility.enrichment_allowed:
            warnings.append(
                "Enrichment is disabled because inferential differential-expression "
                "results are unavailable in QC-only mode."
            )
    if not resolved_output:
        warnings.append("No output directory set; run uses --output.")
    if resolved_output:
        parent = resolved_output if os.path.exists(resolved_output) else os.path.dirname(resolved_output)
        if parent and not os.access(parent, os.W_OK):
            errors.append(f"Output directory is not writable: {resolved_output}")
        _check_output_writable(resolved_output, errors)
    if engine == "real":
        errors.extend(tool_check_errors(skip_toolcheck))
    return ValidationResult(
        config=config,
        input_dir=resolved_input,
        output_dir=resolved_output,
        eligibility=eligibility,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
