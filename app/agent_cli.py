"""Typer commands for Harako's vendor-neutral agent interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from .agent import (
    AgentInterfaceError,
    artifact_inventory,
    build_agent_context,
    create_plan,
    dry_run_plan,
    execute_plan,
    init_post_analysis,
    inspect_input,
    load_inspection,
    load_plan,
    propose_samples,
    propose_samples_from_inspection,
    run_status,
    validate_plan_payload,
    write_sample_table,
)
from .agent_contracts import response, write_document


agent_app = typer.Typer(help="Stable machine-readable planning and run inspection for local automation.")

EXIT_INVALID = 2
EXIT_APPROVAL = 3
EXIT_EXECUTION = 4
EXIT_NOT_FOUND = 5


def _emit(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _fail(exc: Exception, *, code: int = EXIT_INVALID, reason_code: str = "invalid_input") -> None:
    _emit(response({"ok": False, "reason_code": reason_code, "errors": [str(exc)], "warnings": []}))
    raise typer.Exit(code=code)


@agent_app.command("inspect-input")
def inspect_input_command(
    input_dir: Path = typer.Option(..., "--input", exists=False, file_okay=False),
    output: Optional[Path] = typer.Option(None, "--output", dir_okay=False),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    try:
        payload = inspect_input(input_dir)
        if output:
            write_document(output, payload, force=force)
    except (AgentInterfaceError, OSError) as exc:
        _fail(exc)
    _emit(payload)


@agent_app.command("propose-samples")
def propose_samples_command(
    inspection: Optional[Path] = typer.Option(None, "--inspection", exists=False, dir_okay=False),
    input_dir: Optional[Path] = typer.Option(None, "--input", exists=False, file_okay=False),
    condition_map: Optional[Path] = typer.Option(None, "--condition-map", exists=False, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
    report: Optional[Path] = typer.Option(None, "--report", dir_okay=False),
    force: bool = typer.Option(False, "--force", "--overwrite"),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    try:
        if (inspection is None) == (input_dir is None):
            raise AgentInterfaceError("Provide exactly one of --inspection or --input.")
        payload = (
            propose_samples_from_inspection(load_inspection(inspection), condition_map)
            if inspection is not None
            else propose_samples(input_dir, condition_map)
        )
        write_sample_table(output, payload["samples"], overwrite=force)
        payload["sample_table"] = str(output.expanduser().resolve())
        if report:
            write_document(report, payload, force=force)
    except (AgentInterfaceError, OSError) as exc:
        _fail(exc)
    _emit(payload)


@agent_app.command("plan")
def plan_command(
    sample_table: Path = typer.Option(..., "--samples", "--sample-table", exists=False, dir_okay=False),
    input_root: Path = typer.Option(..., "--input", "--input-root", exists=False, file_okay=False),
    output_root: Path = typer.Option(..., "--output", "--output-root", file_okay=False),
    project_name: str = typer.Option(..., "--project-name"),
    species: str = typer.Option(..., "--species"),
    ref_preset: str = typer.Option(..., "--ref-preset"),
    contrast_mode: str = typer.Option("ref", "--contrast-mode"),
    contrast_ref: Optional[str] = typer.Option(None, "--contrast-ref"),
    contrast_pair: list[str] = typer.Option([], "--contrast-pair", help="Repeat as A,B for select mode."),
    threads: int = typer.Option(1, "--threads", min=1),
    plan_file: Path = typer.Option(..., "--plan", "--json-output", dir_okay=False),
    ref_release: str = typer.Option("pinned", "--ref-release"),
    ref_cache_dir: Optional[Path] = typer.Option(None, "--ref-cache-dir", file_okay=False),
    ref_manifest: Optional[Path] = typer.Option(None, "--ref-manifest", dir_okay=False),
    enable_enrichment: bool = typer.Option(False, "--enable-enrichment"),
    force: bool = typer.Option(False, "--force", "--overwrite"),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    try:
        pairs = []
        for value in contrast_pair:
            parts = [part.strip() for part in value.split(",")]
            if len(parts) != 2 or not all(parts):
                raise AgentInterfaceError(f"Invalid --contrast-pair '{value}'; expected A,B.")
            pairs.append(parts)
        payload = create_plan(
            sample_table=sample_table,
            input_root=input_root,
            output_root=output_root,
            project_name=project_name,
            species=species,
            ref_preset=ref_preset,
            contrast_mode=contrast_mode,
            contrast_ref=contrast_ref,
            contrast_pairs=pairs,
            ref_release=ref_release,
            ref_cache_dir=ref_cache_dir,
            ref_manifest=ref_manifest,
            enable_enrichment=enable_enrichment,
            threads=threads,
        )
        write_document(plan_file, payload, force=force)
    except (AgentInterfaceError, OSError, ValueError) as exc:
        _fail(exc)
    _emit(payload)


@agent_app.command("validate-plan")
def validate_plan_command(
    plan: Path = typer.Option(..., "--plan", exists=False, dir_okay=False),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    try:
        payload = validate_plan_payload(load_plan(plan))
    except AgentInterfaceError as exc:
        _fail(exc)
    _emit(payload)
    if not payload["valid"]:
        raise typer.Exit(code=EXIT_INVALID)
    if not payload["executable"]:
        raise typer.Exit(code=EXIT_APPROVAL)


@agent_app.command("dry-run")
def dry_run_command(
    plan: Path = typer.Option(..., "--plan", exists=False, dir_okay=False),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    try:
        payload = dry_run_plan(load_plan(plan))
    except AgentInterfaceError as exc:
        _fail(exc, code=EXIT_APPROVAL, reason_code="plan_not_executable")
    except Exception as exc:
        _fail(AgentInterfaceError(f"Snakemake dry-run failed: {exc}"), code=EXIT_EXECUTION, reason_code="dry_run_failed")
    _emit(payload)
    if not payload["valid"]:
        raise typer.Exit(code=EXIT_EXECUTION)


def _execute_command(plan: Path, approve: Optional[str]) -> None:
    try:
        envelope = load_plan(plan)
    except AgentInterfaceError as exc:
        _fail(exc)
    if approve is None:
        _emit(
            response(
                {
                    "executed": False,
                    "reason_code": "approval_required",
                    "plan_id": envelope.get("plan_id"),
                    "approval_hash": envelope.get("approval_hash"),
                    "analysis_mode": (envelope.get("analysis_plan") or {}).get("mode"),
                    "message": "Execution requires --approve with this exact approval_hash.",
                }
            )
        )
        raise typer.Exit(code=EXIT_APPROVAL)
    try:
        result = execute_plan(envelope, approval=approve)
    except AgentInterfaceError as exc:
        _fail(exc, code=EXIT_APPROVAL, reason_code="approval_or_validation_failed")
    except Exception as exc:
        _fail(AgentInterfaceError(f"Pipeline execution failed: {exc}"), code=EXIT_EXECUTION, reason_code="execution_failed")
    _emit(result)
    if result["exit_code"] != 0:
        raise typer.Exit(code=EXIT_EXECUTION)


@agent_app.command("execute")
def execute_command(
    plan: Path = typer.Option(..., "--plan", exists=False, dir_okay=False),
    approve: Optional[str] = typer.Option(None, "--approve"),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    _execute_command(plan, approve)


@agent_app.command("run-plan", hidden=True)
def run_plan_compatibility_command(
    plan: Path = typer.Option(..., "--plan", exists=False, dir_okay=False),
    approve: Optional[str] = typer.Option(None, "--approve", "--confirm-plan"),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    _execute_command(plan, approve)


@agent_app.command("status")
def status_command(
    run_dir: Path = typer.Option(..., "--run-dir", "--run", exists=False, file_okay=False),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    try:
        payload = run_status(run_dir)
    except AgentInterfaceError as exc:
        _fail(exc, code=EXIT_NOT_FOUND, reason_code="run_not_found")
    _emit(payload)


@agent_app.command("artifacts")
def artifacts_command(
    run_dir: Path = typer.Option(..., "--run-dir", "--run", exists=False, file_okay=False),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    try:
        payload = artifact_inventory(run_dir)
    except AgentInterfaceError as exc:
        _fail(exc, code=EXIT_NOT_FOUND, reason_code="run_not_found")
    _emit(payload)


@agent_app.command("context")
def context_command(
    run_dir: Path = typer.Option(..., "--run-dir", "--run", exists=False, file_okay=False),
    output: Optional[Path] = typer.Option(None, "--output", dir_okay=False),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    try:
        payload = build_agent_context(run_dir)
        if output:
            write_document(output, payload, force=force)
    except (AgentInterfaceError, OSError) as exc:
        _fail(exc, code=EXIT_NOT_FOUND if "run" in str(exc).lower() else EXIT_INVALID)
    _emit(payload)


def _post_analysis_command(run_dir: Path, name: str, question: str) -> None:
    try:
        payload = init_post_analysis(run_dir, name, question)
    except AgentInterfaceError as exc:
        _fail(exc, code=EXIT_NOT_FOUND if "run" in str(exc).lower() else EXIT_INVALID)
    _emit(payload)


@agent_app.command("post-analysis-init")
def post_analysis_init_command(
    run_dir: Path = typer.Option(..., "--run-dir", "--run", exists=False, file_okay=False),
    name: str = typer.Option(..., "--name"),
    question: str = typer.Option("", "--question"),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    _post_analysis_command(run_dir, name, question)


@agent_app.command("init-post-analysis", hidden=True)
def init_post_analysis_compatibility_command(
    run_dir: Path = typer.Option(..., "--run-dir", "--run", exists=False, file_okay=False),
    name: str = typer.Option(..., "--name"),
    question: str = typer.Option("", "--question"),
    json_output: bool = typer.Option(True, "--json", hidden=True),
) -> None:
    del json_output
    _post_analysis_command(run_dir, name, question)
