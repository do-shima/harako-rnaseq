"""Root Typer composition and backward-compatible internal imports."""

from __future__ import annotations

from pathlib import Path

import typer

from app.adapters.snakemake import add_compatible_flags, parse_version, snakemake_version_text
from app.agent_cli import agent_app
from app.commands.execution import run_command, run_id_command, run_impl, snakemake_version_command
from app.commands.setup import fetch_command, init_command
from app.commands.validation import validate_command
from app.core.fastq import FASTQ_EXTS
from app.services import configuration as config_service
from app.services import provenance as provenance_service
from app.services.input_files import scan_fastq
from app.version import VERSION


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(VERSION)
        raise typer.Exit()


app = typer.Typer(help="RNA-seq pipeline CLI")
app.add_typer(agent_app, name="agent")


@app.callback()
def _root_options(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the Harako-RNAseq version and exit.",
    ),
) -> None:
    del version


# Stable command names and option declarations live in the command adapters.
init = app.command("init")(init_command)
validate = app.command("validate")(validate_command)
run = app.command("run")(run_command)
run_id_cmd = app.command("run-id")(run_id_command)
snakemake_version = app.command("snakemake-version")(snakemake_version_command)
fetch = app.command("fetch")(fetch_command)


# Compatibility helpers retained for focused tests and existing local callers.
_abs_path = config_service.absolute_path
_resolve_path = config_service.resolve_path
_load_yaml = config_service.load_yaml
_write_yaml = config_service.write_yaml
_parse_sample_table = config_service.parse_sample_table
_contrast_levels_from_samples = config_service.contrast_levels
_canonical_pair = config_service.canonical_contrast
_resolve_contrasts = config_service.resolve_contrasts
_resolve_fastq_from_config = config_service.resolve_fastq_from_config
_resolve_run_cfg = config_service.resolve_run_config
_resolve_reference_cfg = config_service.resolve_reference_config
_git_rev = provenance_service.git_revision
_sha256_path = provenance_service.sha256_path
_build_manifest_payload = provenance_service.build_manifest_payload
_manifest_run_id = provenance_service.manifest_run_id
_run_impl = run_impl


def _scan_fastq(root: str) -> list[str]:
    path = Path(root) if root else None
    if path is None or not path.is_dir():
        return []
    return [str(item) for item in scan_fastq(path)]


def _snakemake_version() -> str:
    return snakemake_version_text()


def _parse_version(value: str) -> tuple[int, int, int]:
    return parse_version(value)


def _filter_snakemake_flags(
    command: list[str],
    printshellcmds: bool,
    latency_wait: int,
    rerun_incomplete: bool,
    quiet_categories: list[str] | None = None,
) -> None:
    for warning in add_compatible_flags(
        command,
        printshellcmds=printshellcmds,
        latency_wait=latency_wait,
        rerun_incomplete=rerun_incomplete,
        quiet_categories=quiet_categories,
    ):
        typer.echo(warning)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
