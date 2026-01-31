import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
import yaml

from .run import RunArgs, build_snakemake_cmd, run_pipeline


app = typer.Typer(help="RNA-seq pipeline CLI")


def _abs_path(value: str):
    if value is None:
        return None
    return os.path.abspath(os.path.expanduser(value))


def _load_yaml(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _write_yaml(payload: dict, path: str):
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def _parse_sample_table(path: str):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        header = handle.readline().strip().split("\t")
        for line in handle:
            if not line.strip():
                continue
            values = line.rstrip("\n").split("\t")
            row = dict(zip(header, values))
            rows.append(row)
    return rows


def _validate_paths(paths, errors, label):
    for path in paths:
        if path and not os.path.exists(path):
            errors.append(f"Missing {label} file: {path}")


def _check_tools(skip_toolcheck: bool, errors):
    if skip_toolcheck:
        return
    for tool in ("fastp", "salmon", "Rscript"):
        if shutil.which(tool) is None:
            errors.append(f"Required tool not found in PATH: {tool}")
    if shutil.which("Rscript"):
        probe = subprocess.run(
            ["Rscript", "-e", "library(DESeq2); library(tximport)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode != 0:
            errors.append("R packages missing: DESeq2 and/or tximport (install inside container).")


def _resolve_fastq_from_config(cfg: dict):
    fastq = cfg.get("fastq") or {}
    fastq1 = cfg.get("fastq1") or {}
    fastq2 = cfg.get("fastq2") or {}
    if fastq1 or fastq2:
        return fastq1, fastq2
    return fastq, {}


@app.command("init")
def init(
    out: str = typer.Option("config.yaml", "--out", help="Output config path"),
):
    typer.echo("Interactive setup (no network downloads).")
    engine = typer.prompt("Engine", default="real", show_default=True)
    paired = typer.confirm("Paired-end reads?", default=False)

    sample_ids_raw = typer.prompt("Sample IDs (comma-separated)")
    sample_ids = [item.strip() for item in sample_ids_raw.split(",") if item.strip()]
    if not sample_ids:
        raise typer.Exit(code=1)

    conditions = {}
    for sample in sample_ids:
        conditions[sample] = typer.prompt(f"Condition for {sample}")

    samples_path = _abs_path("samples.tsv")
    with open(samples_path, "w", encoding="utf-8") as handle:
        header = ["sample", "condition", "fastq1"]
        if paired:
            header.append("fastq2")
        handle.write("\t".join(header) + "\n")
        for sample in sample_ids:
            fq1 = typer.prompt(f"FASTQ path for {sample} (R1)" if paired else f"FASTQ path for {sample}")
            fq2 = ""
            if paired:
                fq2 = typer.prompt(f"FASTQ path for {sample} (R2)")
            row = [sample, conditions[sample], _abs_path(fq1)]
            if paired:
                row.append(_abs_path(fq2))
            handle.write("\t".join(row) + "\n")

    outdir = _abs_path(typer.prompt("Output directory", default="out"))

    ref_choice = typer.prompt(
        "Reference mode (fasta_gtf, preset, transcripts_only)",
        default="fasta_gtf",
    )
    ref_block = {}
    ref_preset = None
    ref_manifest = None
    if ref_choice == "preset":
        ref_preset = typer.prompt("Preset name (e.g. human_gencode)")
        ref_manifest = _abs_path(typer.prompt("Manifest path", default=str(Path("workflow") / "ref_manifest.yaml")))
        ref_cache = typer.prompt("Cache directory", default="refs_cache")
        typer.echo(
            "Run fetch explicitly: python -m app fetch --preset "
            f"{ref_preset} --release pinned --cache-dir {ref_cache}"
        )
    elif ref_choice == "transcripts_only":
        ref_block["transcripts_fasta"] = _abs_path(typer.prompt("Transcripts FASTA (.fa/.fa.gz)"))
    else:
        ref_block["transcripts_fasta"] = _abs_path(typer.prompt("Transcripts FASTA (.fa/.fa.gz)"))
        ref_block["genome_fasta"] = _abs_path(typer.prompt("Genome FASTA (.fa/.fa.gz)"))
        ref_block["gtf"] = _abs_path(typer.prompt("Annotation GTF (.gtf/.gtf.gz)"))

    contrasts_raw = typer.prompt("Contrasts (comma-separated A_vs_B, optional)", default="")
    contrasts = [item.strip() for item in contrasts_raw.split(",") if item.strip()]
    threads = typer.prompt("Threads", default="1")

    payload = {
        "engine": engine,
        "samples": sample_ids,
        "sample_table": samples_path,
        "output": outdir,
        "ref": ref_block,
        "threads": int(threads),
    }
    if ref_preset:
        payload["ref_preset"] = ref_preset
    if ref_manifest:
        payload["ref_manifest"] = ref_manifest
    if contrasts:
        payload["contrasts"] = contrasts

    _write_yaml(payload, _abs_path(out))
    typer.echo(f"Wrote {out} and {samples_path}")


@app.command("validate")
def validate(
    config: str = typer.Option(..., "--config", help="Config YAML path"),
    skip_toolcheck: bool = typer.Option(False, "--skip-toolcheck", help="Skip checking tools in PATH"),
):
    cfg = _load_yaml(config)
    errors = []
    warnings = []

    engine = cfg.get("engine", "real")
    samples = cfg.get("samples") or []

    sample_table = cfg.get("sample_table")
    if sample_table:
        sample_table = _abs_path(sample_table)
        if not os.path.exists(sample_table):
            errors.append(f"Sample table not found: {sample_table}")
        else:
            rows = _parse_sample_table(sample_table)
            samples = [row.get("sample") for row in rows if row.get("sample")]
            if not samples:
                errors.append("Sample table has no samples.")
            conditions = [row.get("condition") for row in rows if row.get("condition")]
            if engine == "real" and len(set(conditions)) < 2:
                errors.append("Need at least two conditions for DESeq2 (engine=real).")
            fastq1 = [row.get("fastq1") for row in rows]
            fastq2 = [row.get("fastq2") for row in rows]
            _validate_paths([_abs_path(p) for p in fastq1 if p], errors, "FASTQ")
            if any(fastq2):
                _validate_paths([_abs_path(p) for p in fastq2 if p], errors, "FASTQ (R2)")
                if not all(fastq2):
                    warnings.append("Paired-end FASTQ2 missing for some samples.")
            for idx, row in enumerate(rows):
                if row.get("fastq2") and not row.get("fastq1"):
                    errors.append(f"Sample {row.get('sample') or idx} has FASTQ2 but no FASTQ1.")
    else:
        if not samples:
            errors.append("No samples defined in config.")
        conditions = cfg.get("conditions") or {}
        if engine == "real" and len(set(conditions.values())) < 2:
            errors.append("Need at least two conditions for DESeq2 (engine=real).")
        fastq1, fastq2 = _resolve_fastq_from_config(cfg)
        for sample in samples:
            if sample not in fastq1:
                errors.append(f"Missing FASTQ for sample: {sample}")
            else:
                _validate_paths([_abs_path(fastq1[sample])], errors, "FASTQ")
            if fastq2 and sample in fastq2:
                _validate_paths([_abs_path(fastq2[sample])], errors, "FASTQ (R2)")
            elif fastq2:
                warnings.append(f"Missing FASTQ2 for sample: {sample}")

    ref = cfg.get("ref") or {}
    transcripts = ref.get("transcripts_fasta")
    genome = ref.get("genome_fasta")
    gtf = ref.get("gtf")
    if engine == "real":
        if not transcripts:
            errors.append("transcripts_fasta is required for engine=real.")
    _validate_paths([_abs_path(p) for p in (transcripts, genome, gtf) if p], errors, "reference")

    outdir = cfg.get("output") or cfg.get("outdir") or None
    if outdir:
        outdir = _abs_path(outdir)
    else:
        warnings.append("No output directory set; run uses --output.")

    if outdir:
        parent = outdir if os.path.exists(outdir) else os.path.dirname(outdir)
        if parent and not os.access(parent, os.W_OK):
            errors.append(f"Output directory is not writable: {outdir}")

    if engine == "real":
        _check_tools(skip_toolcheck, errors)

    if warnings:
        typer.echo("Warnings:")
        for warning in warnings:
            typer.echo(f"- {warning}")

    if errors:
        typer.echo("Errors:")
        for error in errors:
            typer.echo(f"- {error}")
        raise typer.Exit(code=2)

    typer.echo("Validation OK.")


@app.command("run")
def run(
    config: str = typer.Option(..., "--config", help="Config YAML path"),
    input_dir: str = typer.Option(".", "--input", help="Input directory"),
    output_dir: str = typer.Option(None, "--output", help="Output directory"),
    align: str = typer.Option("none", "--align", help="Alignment mode"),
    engine: str = typer.Option("", "--engine", help="Override engine"),
    threads: str = typer.Option("", "--threads", help="Override threads"),
    no_validate: bool = typer.Option(False, "--no-validate", help="Skip validation"),
):
    cfg = _load_yaml(config)
    if not no_validate:
        validate(config=config, skip_toolcheck=False)

    final_output = output_dir or cfg.get("output") or "out"
    args = RunArgs(
        input=_abs_path(input_dir),
        output=_abs_path(final_output),
        config=_abs_path(config),
        align=align,
        engine=engine,
        threads=threads,
    )
    cmd = build_snakemake_cmd(args)
    typer.echo("Running: " + " ".join(cmd))
    raise typer.Exit(code=run_pipeline(args))


@app.command("fetch")
def fetch(
    preset: str = typer.Option(..., "--preset"),
    release: str = typer.Option("pinned", "--release"),
    cache_dir: str = typer.Option("refs_cache", "--cache-dir"),
    out_json: str = typer.Option("", "--out-json"),
    update_config: str = typer.Option("", "--update-config", help="Config YAML to update"),
):
    script_path = os.path.join(os.path.dirname(__file__), os.pardir, "scripts", "fetch_reference_preset.py")
    cmd = [
        sys.executable,
        script_path,
        "--preset",
        preset,
        "--release",
        release,
        "--cache-dir",
        _abs_path(cache_dir),
    ]
    if out_json:
        cmd.extend(["--out-json", _abs_path(out_json)])
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout)
        raise typer.Exit(code=result.returncode)

    payload = result.stdout.strip()
    if out_json:
        payload_path = _abs_path(out_json)
        with open(payload_path, "r", encoding="utf-8") as handle:
            payload = handle.read()

    if update_config:
        cfg_path = _abs_path(update_config)
        cfg = _load_yaml(cfg_path)
        resolved = yaml.safe_load(payload)
        cfg.setdefault("ref", {})
        cfg["ref"]["transcripts_fasta"] = resolved.get("transcripts_fasta")
        cfg["ref"]["genome_fasta"] = resolved.get("genome_fasta")
        cfg["ref"]["gtf"] = resolved.get("gtf")
        _write_yaml(cfg, cfg_path)
        typer.echo(f"Updated config: {cfg_path}")
    else:
        typer.echo(payload)


def main():
    app()


if __name__ == "__main__":
    main()
