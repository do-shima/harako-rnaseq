"""Application service for validated Snakemake execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from app.adapters.snakemake import RunArgs, add_compatible_flags, build_snakemake_cmd, run_pipeline
from app.services.configuration import absolute_path, load_yaml, resolve_run_config
from app.services.provenance import write_run_provenance
from app.services.validation import validate_configuration


@dataclass(frozen=True)
class PipelineRequest:
    config: str
    input_dir: str | None = None
    output_dir: str | None = None
    align: str = "none"
    engine: str = ""
    threads: str = ""
    run_id: str = ""
    validate: bool = True
    resume: bool = False
    force: bool = False
    rerun_incomplete: bool = False
    keep_going: bool = False
    printshellcmds: bool = False
    reason: bool = False
    quiet_reason: bool = False
    latency_wait: int = 60
    dry_run: bool = False
    forceall: bool = False
    forcerun: str = ""
    use_conda: bool = False


class PipelineRequestError(ValueError):
    def __init__(self, message: str, *, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


def execute_pipeline(
    request: PipelineRequest,
    *,
    output_stream: TextIO | None = None,
    message_sink: Callable[[str], None] | None = None,
) -> int:
    emit = message_sink or (lambda _message: None)
    config = load_yaml(request.config)
    if request.validate:
        validation = validate_configuration(
            request.config,
            input_dir=request.input_dir,
            output_dir=request.output_dir,
            skip_toolcheck=False,
        )
        for warning in validation.warnings:
            emit(f"Warning: {warning}")
        if validation.errors:
            raise PipelineRequestError("; ".join(validation.errors))

    final_input = request.input_dir or config.get("input") or "."
    final_output = request.output_dir or config.get("output") or "out"
    effective_engine = request.engine or config.get("engine", "real")
    rerun_incomplete = request.rerun_incomplete
    if effective_engine == "real":
        if not final_output or not final_output.strip() or final_output == "/":
            raise PipelineRequestError("Refusing to run: output directory is empty or root '/'.")
        final_output_absolute = absolute_path(final_output)
        if os.path.exists(final_output_absolute):
            entries = [path for path in os.listdir(final_output_absolute) if path not in (".", "..")]
            if entries and not (request.resume or request.force):
                raise PipelineRequestError("Output directory is not empty; use --resume or --force to proceed.")
        if request.resume:
            rerun_incomplete = True

    effective_threads = request.threads or str(config.get("threads") or "")
    args = RunArgs(
        input=absolute_path(final_input),
        output=absolute_path(final_output),
        config=absolute_path(request.config),
        align=request.align,
        engine=effective_engine,
        threads=effective_threads,
    )
    command = build_snakemake_cmd(args)
    if effective_engine == "real":
        if request.keep_going:
            command.append("--keep-going")
        quiet_categories = ["reason"] if request.quiet_reason or not request.reason else []
        for warning in add_compatible_flags(
            command,
            printshellcmds=request.printshellcmds,
            latency_wait=request.latency_wait,
            rerun_incomplete=rerun_incomplete,
            quiet_categories=quiet_categories,
        ):
            emit(warning)
        if request.dry_run:
            command.append("-n")
        if request.forceall:
            command.append("--forceall")
        if request.forcerun:
            command.extend(["--forcerun", request.forcerun])
        if request.use_conda:
            command.append("--use-conda")
        resolved = resolve_run_config(
            config,
            request.config,
            final_input,
            final_output,
            request.align,
            request.engine or effective_engine,
            effective_threads,
            request.use_conda,
        )
        write_run_provenance(
            absolute_path(final_output),
            command,
            resolved,
            request.config,
            run_id_override=request.run_id,
            warning_sink=emit,
        )
    emit("Running: " + " ".join(command))
    return run_pipeline(args, cmd=command, output_stream=output_stream)
