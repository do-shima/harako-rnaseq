"""CLI adapters for run, run identity, and Snakemake version commands."""

from __future__ import annotations

import typer

from app.adapters.snakemake import snakemake_version_text
from app.commands.validation import validate_command
from app.services.configuration import load_yaml, resolve_run_config
from app.services.pipeline_execution import PipelineRequest, PipelineRequestError, execute_pipeline
from app.services.provenance import build_manifest_payload, manifest_run_id


def run_impl(
    *,
    config: str,
    input_dir: str | None = None,
    output_dir: str | None = None,
    align: str = "none",
    engine: str = "",
    threads: str = "",
    run_id: str = "",
    no_validate: bool = False,
    resume: bool = False,
    force: bool = False,
    rerun_incomplete: bool = False,
    keep_going: bool = False,
    printshellcmds: bool = False,
    reason: bool = False,
    quiet_reason: bool = False,
    latency_wait: int = 60,
    dry_run: bool = False,
    forceall: bool = False,
    forcerun: str = "",
    use_conda: bool = False,
    output_stream=None,
) -> int:
    if not no_validate:
        validate_command(config=config, input_dir=input_dir, output_dir=output_dir, skip_toolcheck=False)
    request = PipelineRequest(
        config=config,
        input_dir=input_dir,
        output_dir=output_dir,
        align=align,
        engine=engine,
        threads=threads,
        run_id=run_id,
        validate=False,
        resume=resume,
        force=force,
        rerun_incomplete=rerun_incomplete,
        keep_going=keep_going,
        printshellcmds=printshellcmds,
        reason=reason,
        quiet_reason=quiet_reason,
        latency_wait=latency_wait,
        dry_run=dry_run,
        forceall=forceall,
        forcerun=forcerun,
        use_conda=use_conda,
    )
    try:
        return execute_pipeline(request, output_stream=output_stream, message_sink=typer.echo)
    except PipelineRequestError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=exc.exit_code) from exc


def run_command(
    config: str = typer.Option(..., "--config", help="Config YAML path"),
    input_dir: str = typer.Option(None, "--input", help="Input directory"),
    output_dir: str = typer.Option(None, "--output", help="Output directory"),
    align: str = typer.Option("none", "--align", help="Alignment mode"),
    engine: str = typer.Option("", "--engine", help="Override engine"),
    threads: str = typer.Option("", "--threads", help="Override threads"),
    run_id: str = typer.Option("", "--run-id", help="Run identifier to record in manifest"),
    no_validate: bool = typer.Option(False, "--no-validate", help="Skip validation"),
    resume: bool = typer.Option(False, "--resume", help="Resume run (rerun incomplete)"),
    force: bool = typer.Option(False, "--force", help="Allow overwrite in non-empty output"),
    rerun_incomplete: bool = typer.Option(False, "--rerun-incomplete", help="Rerun incomplete jobs"),
    keep_going: bool = typer.Option(False, "--keep-going", help="Keep going after errors"),
    printshellcmds: bool = typer.Option(False, "--printshellcmds", help="Print shell commands"),
    reason: bool = typer.Option(False, "--reason", help="Compatibility flag for reason output (Snakemake --reason is not used)"),
    quiet_reason: bool = typer.Option(False, "--quiet-reason", help="Suppress reason output via Snakemake --quiet reason"),
    latency_wait: int = typer.Option(60, "--latency-wait", help="Seconds to wait for filesystem latency"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Snakemake dry run (-n)"),
    forceall: bool = typer.Option(False, "--forceall", help="Force execution of all rules"),
    forcerun: str = typer.Option("", "--forcerun", help="Force execution of specific rule"),
    use_conda: bool = typer.Option(False, "--use-conda", help="Enable Snakemake conda integration"),
) -> None:
    raise typer.Exit(
        code=run_impl(
            config=config,
            input_dir=input_dir,
            output_dir=output_dir,
            align=align,
            engine=engine,
            threads=threads,
            run_id=run_id,
            no_validate=no_validate,
            resume=resume,
            force=force,
            rerun_incomplete=rerun_incomplete,
            keep_going=keep_going,
            printshellcmds=printshellcmds,
            reason=reason,
            quiet_reason=quiet_reason,
            latency_wait=latency_wait,
            dry_run=dry_run,
            forceall=forceall,
            forcerun=forcerun,
            use_conda=use_conda,
        )
    )


def run_id_command(
    config: str = typer.Option(..., "--config", help="Config YAML path"),
    input_dir: str = typer.Option(None, "--input", help="Input directory"),
    output_dir: str = typer.Option(None, "--output", help="Output directory (optional; excluded from hash)"),
    align: str = typer.Option("none", "--align", help="Alignment mode"),
    engine: str = typer.Option("", "--engine", help="Override engine"),
    threads: str = typer.Option("", "--threads", help="Override threads"),
    use_conda: bool = typer.Option(False, "--use-conda", help="Enable Snakemake conda integration"),
) -> None:
    loaded = load_yaml(config)
    final_input = input_dir or loaded.get("input") or "."
    final_output = output_dir or loaded.get("output") or ""
    resolved = resolve_run_config(
        loaded,
        config,
        final_input,
        final_output,
        align,
        engine or loaded.get("engine", ""),
        threads or str(loaded.get("threads") or ""),
        use_conda,
    )
    typer.echo(manifest_run_id(build_manifest_payload(config, resolved)))


def snakemake_version_command() -> None:
    typer.echo(snakemake_version_text())
