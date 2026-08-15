"""Read-only status, artifact, and sanitized-context services."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

import yaml

from app.agent_contracts import AgentInterfaceError, response
from app.core.protocol import LEGACY_UNSPECIFIED
from app.services.configuration import parse_sample_table

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


require_run_dir = _run_dir


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
    legacy_handoff = bool(de_status.get("legacy_handoff")) or (
        "library_protocol" not in config and "library_protocol" not in de_status
    )
    library_protocol = (
        de_status.get("library_protocol")
        or config.get("library_protocol")
        or LEGACY_UNSPECIFIED
    )
    handoff_method = de_status.get("tximport_handoff_method")
    if legacy_handoff and not handoff_method:
        handoff_method = "historical_counts_matrix_without_length_offset"
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
            "library_protocol": library_protocol,
            "tximport_handoff_method": handoff_method,
            "counts_from_abundance": de_status.get("counts_from_abundance"),
            "length_offset_used": de_status.get("length_offset_used"),
            "legacy_handoff": legacy_handoff,
            "scientific_warning": de_status.get("scientific_warning") or (
                "This run predates explicit library protocol selection; create a new run for reanalysis."
                if legacy_handoff else None
            ),
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
        rows = [{"sample": row["sample"], "condition": row["condition"]} for row in parse_sample_table(table)]
    return response(
        {
            "purpose": "Local agent index; not intended for automatic cloud upload.",
            "run": {
                "run_id": status.get("run_id"),
                "project_name": status.get("project_name"),
                "analysis_mode": status.get("analysis_mode"),
                "library_protocol": status.get("library_protocol"),
                "tximport_handoff_method": status.get("tximport_handoff_method"),
                "length_offset_used": status.get("length_offset_used"),
                "legacy_handoff": status.get("legacy_handoff"),
                "scientific_warning": status.get("scientific_warning"),
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

