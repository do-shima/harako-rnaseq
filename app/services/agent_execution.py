"""Approval-gated agent dry-run and execution services."""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml

from app.agent_contracts import (
    AGENT_INTERFACE_VERSION,
    AgentInterfaceError,
    approval_hash_for,
    response,
    utc_now,
    write_document,
)
from app.services.agent_inputs import _resolve_under_root, write_sample_table
from app.services.agent_planning import validate_plan_payload
from app.services.pipeline_execution import PipelineRequest, PipelineRequestError, execute_pipeline
from app.services.run_contract import write_frozen_run_config

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
        "library_protocol": plan["library_protocol"],
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
    try:
        return int(
            execute_pipeline(
                PipelineRequest(
                    config=str(config_path),
                    input_dir=plan["input_root"],
                    output_dir=str(run_dir),
                    engine="real",
                    threads=str(plan["resources"]["threads"]),
                    force=True,
                ),
                output_stream=sys.stderr,
                message_sink=lambda message: print(message, file=sys.stderr),
            )
        )
    except PipelineRequestError as exc:
        return int(exc.exit_code)


def dry_run_plan(
    plan: dict[str, Any], *, runner: Callable[[Path, dict[str, Any], Path], tuple[int, str]] | None = None
) -> dict[str, Any]:
    validation = validate_plan_payload(plan)
    if not validation["valid"] or not validation["executable"]:
        raise AgentInterfaceError("Plan is not executable: " + "; ".join(validation["errors"] + validation["unresolved"]))

    def default_runner(config_path: Path, envelope: dict[str, Any], output_dir: Path) -> tuple[int, str]:
        log_path = output_dir.parent / "snakemake-dry-run.log"
        with log_path.open("w+", encoding="utf-8") as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                code = int(
                    execute_pipeline(
                        PipelineRequest(
                            config=str(config_path),
                            input_dir=envelope["input_root"],
                            output_dir=str(output_dir),
                            engine="real",
                            threads=str(envelope["resources"]["threads"]),
                            validate=False,
                            force=True,
                            quiet_reason=True,
                            dry_run=True,
                        ),
                        output_stream=stream,
                        message_sink=lambda message: print(message, file=stream),
                    )
                )
            except PipelineRequestError as exc:
                code = int(exc.exit_code)
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
