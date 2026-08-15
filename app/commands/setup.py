"""Interactive local project setup and explicit reference-fetch adapters."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
import yaml

from app.adapters.process import run_capture
from app.core.analysis import analysis_plan_from_rows
from app.core.protocol import resolve_library_protocol
from app.services.configuration import absolute_path, load_yaml, write_yaml


def init_command(
    out: str = typer.Option("config.yaml", "--out", help="Output config path"),
    input_base: str = typer.Option("", "--input-base", help="Optional prefix for FASTQ paths"),
) -> None:
    typer.echo("Interactive setup (no network downloads).")
    engine = typer.prompt("Engine", default="real", show_default=True)
    paired = typer.confirm("Paired-end reads?", default=False)
    library_protocol = resolve_library_protocol(typer.prompt("Library protocol (full_length, three_prime_tag)"))
    sample_ids = [item.strip() for item in typer.prompt("Sample IDs (comma-separated)").split(",") if item.strip()]
    if not sample_ids:
        raise typer.Exit(code=1)
    conditions = {sample: typer.prompt(f"Condition for {sample}") for sample in sample_ids}

    output_path = absolute_path(out)
    output_dir = output_path
    if not output_path.lower().endswith((".yaml", ".yml")):
        output_path = os.path.join(output_dir, "config.yaml")
    else:
        output_dir = os.path.dirname(output_path) or "."
    input_base = (input_base.strip() or "/input").rstrip("/\\")
    samples_path = os.path.join(output_dir, "metadata", "samples.tsv")
    os.makedirs(os.path.dirname(samples_path), exist_ok=True)
    with open(samples_path, "w", encoding="utf-8") as handle:
        header = ["sample", "condition", "fastq1"] + (["fastq2"] if paired else [])
        handle.write("\t".join(header) + "\n")
        for sample in sample_ids:
            fastq1 = typer.prompt(f"FASTQ path for {sample} (R1)" if paired else f"FASTQ path for {sample}").strip()
            fastq2 = typer.prompt(f"FASTQ path for {sample} (R2)").strip() if paired else ""
            for path in (fastq1, fastq2):
                if path and (":" in path or path.startswith("\\")):
                    typer.echo("Warning: Windows-style path detected. Place files under /input and use relative paths.")
            row = [sample, conditions[sample], fastq1] + ([fastq2] if paired else [])
            handle.write("\t".join(row) + "\n")

    reference_choice = typer.prompt("Reference mode (fasta_gtf, preset, transcripts_only)", default="fasta_gtf")
    reference: dict[str, str] = {}
    reference_preset = None
    reference_manifest = None
    if reference_choice == "preset":
        reference_preset = typer.prompt("Preset name (e.g. human_ensembl_grch38)")
        reference_manifest = typer.prompt("Manifest path", default=str(Path("workflow") / "ref_manifest.yaml"))
        reference_cache = typer.prompt("Cache directory", default="refs_cache")
        typer.echo(
            "Run fetch explicitly: python -m app fetch --preset "
            f"{reference_preset} --release pinned --cache-dir {reference_cache}"
        )
    elif reference_choice == "transcripts_only":
        reference["transcripts_fasta"] = typer.prompt("Transcripts FASTA (.fa/.fa.gz)")
    else:
        reference["transcripts_fasta"] = typer.prompt("Transcripts FASTA (.fa/.fa.gz)")
        reference["genome_fasta"] = typer.prompt("Genome FASTA (.fa/.fa.gz)")
        reference["gtf"] = typer.prompt("Annotation GTF (.gtf/.gtf.gz)")
    for value in reference.values():
        if ":" in value or value.startswith("\\"):
            typer.echo("Warning: Windows-style path detected. Place files under /input and use relative paths.")

    contrast_mode = typer.prompt("Contrast mode (ref, pairwise, select, legacy)", default="ref")
    contrast_reference = None
    contrast_pairs: list[list[str]] = []
    contrasts: list[str] = []
    condition_levels = list(dict.fromkeys(conditions.values()))
    if contrast_mode == "ref":
        contrast_reference = typer.prompt("Reference condition", default=condition_levels[0] if condition_levels else "")
    elif contrast_mode == "select":
        typer.echo("Enter contrast pairs as A,B (empty to finish).")
        while True:
            raw = typer.prompt("Pair", default="")
            if not raw:
                break
            parts = [part.strip() for part in raw.split(",") if part.strip()]
            if len(parts) != 2:
                typer.echo("Provide exactly two condition names separated by a comma.")
                continue
            contrast_pairs.append(parts)
    elif contrast_mode not in ("pairwise",):
        contrasts = [item.strip() for item in typer.prompt("Legacy contrasts (comma-separated A_vs_B)", default="").split(",") if item.strip()]

    threads = typer.prompt("Threads", default="1")
    enrichment = None
    if typer.confirm("Advanced options?", default=False) and typer.confirm("Enable enrichment?", default=False):
        methods = [item.strip().upper() for item in typer.prompt("Enrichment methods (comma-separated ORA,GSEA)", default="ORA,GSEA").split(",") if item.strip()]
        enrichment = {
            "enable": True,
            "methods": methods or ["ORA", "GSEA"],
            "alpha": float(typer.prompt("Enrichment alpha (FDR)", default="0.05")),
            "lfc": float(typer.prompt("Enrichment min abs(log2FC)", default="0")),
            "top_terms": int(typer.prompt("Top terms to show", default="15")),
            "rank_metric": typer.prompt("Rank metric (stat)", default="stat"),
        }

    payload = {
        "engine": engine,
        "samples": sample_ids,
        "input": input_base,
        "output": output_dir,
        "sample_table": samples_path,
        "library_protocol": library_protocol,
        "ref": reference,
        "threads": int(threads),
        "contrast_mode": contrast_mode,
    }
    if reference_preset:
        payload["ref_preset"] = reference_preset
    if reference_manifest:
        payload["ref_manifest"] = reference_manifest
    if contrast_reference:
        payload["contrast_ref"] = contrast_reference
    if contrast_pairs:
        payload["contrast_pairs"] = contrast_pairs
    if contrasts:
        payload["contrasts"] = contrasts
    if enrichment:
        payload["enrichment"] = enrichment
    payload["analysis_plan"] = analysis_plan_from_rows(
        [{"sample": sample, "condition": conditions.get(sample, "")} for sample in sample_ids]
    )
    if not payload["analysis_plan"]["eligible_for_de"]:
        payload["requested_analysis_options"] = {
            "contrast_mode": payload.pop("contrast_mode", None),
            "contrast_ref": payload.pop("contrast_ref", None),
            "contrast_pairs": payload.pop("contrast_pairs", None),
            "contrasts": payload.pop("contrasts", None),
            "enrichment": payload.pop("enrichment", None),
        }
    write_yaml(payload, output_path)
    typer.echo(f"Wrote {output_path} and {samples_path}")


def fetch_command(
    preset: str = typer.Option(..., "--preset"),
    release: str = typer.Option("pinned", "--release"),
    cache_dir: str = typer.Option("refs_cache", "--cache-dir"),
    out_json: str = typer.Option("", "--out-json"),
    update_config: str = typer.Option("", "--update-config", help="Config YAML to update"),
) -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_reference_preset.py"
    command = [
        sys.executable,
        str(script_path),
        "--preset",
        preset,
        "--release",
        release,
        "--cache-dir",
        absolute_path(cache_dir),
    ]
    if out_json:
        command.extend(["--out-json", absolute_path(out_json)])
    result = run_capture(command)
    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout)
        raise typer.Exit(code=result.returncode)
    payload = result.stdout.strip()
    if out_json:
        payload = Path(absolute_path(out_json)).read_text(encoding="utf-8")
    if update_config:
        config_path = absolute_path(update_config)
        config = load_yaml(config_path)
        resolved = yaml.safe_load(payload)
        config.setdefault("ref", {})
        config["ref"].update(
            {
                "transcripts_fasta": resolved.get("transcripts_fasta"),
                "genome_fasta": resolved.get("genome_fasta"),
                "gtf": resolved.get("gtf"),
            }
        )
        write_yaml(config, config_path)
        typer.echo(f"Updated config: {config_path}")
    else:
        typer.echo(payload)
