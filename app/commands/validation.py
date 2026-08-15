"""CLI presentation for the neutral validation service."""

from __future__ import annotations

import typer

from app.services.validation import ValidationResult, validate_configuration


def emit_validation(result: ValidationResult) -> None:
    if result.warnings:
        typer.echo("Warnings:")
        for warning in result.warnings:
            typer.echo(f"- {warning}")
    if result.errors:
        typer.echo("Errors:")
        for error in result.errors:
            typer.echo(f"- {error}")
        raise typer.Exit(code=2)
    eligibility = result.eligibility
    typer.echo(f"Analysis mode: {eligibility.mode}")
    typer.echo(f"Reason code: {eligibility.reason_code}")
    typer.echo(
        "Condition counts: "
        + (", ".join(f"{condition}={count}" for condition, count in eligibility.condition_counts.items()) or "none")
    )
    typer.echo(f"Total samples: {eligibility.total_samples}")
    typer.echo("Validation OK.")


def validate_command(
    config: str = typer.Option(..., "--config", help="Config YAML path"),
    input_dir: str = typer.Option(None, "--input", help="Input directory override"),
    output_dir: str = typer.Option(None, "--output", help="Output directory override"),
    skip_toolcheck: bool = typer.Option(False, "--skip-toolcheck", help="Skip checking tools in PATH"),
) -> None:
    emit_validation(
        validate_configuration(
            config,
            input_dir=input_dir,
            output_dir=output_dir,
            skip_toolcheck=skip_toolcheck,
        )
    )
