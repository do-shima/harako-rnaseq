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


def _resolve_path(path: str, indir: str, config_dir: str):
    if path is None:
        return None
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return os.path.abspath(path)
    if indir:
        return os.path.abspath(os.path.join(indir, path))
    if config_dir:
        return os.path.abspath(os.path.join(config_dir, path))
    return os.path.abspath(path)


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


def _snakemake_version():
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "snakemake", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return (proc.stdout or proc.stderr).strip().splitlines()[0]
    except OSError:
        return "unknown"
    return "unknown"


def _parse_version(value):
    parts = []
    for chunk in value.replace("snakemake", "").strip().split("."):
        try:
            parts.append(int("".join([c for c in chunk if c.isdigit()])))
        except ValueError:
            break
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _filter_snakemake_flags(cmd, reason, printshellcmds, latency_wait, rerun_incomplete):
    version_str = _snakemake_version()
    version = _parse_version(version_str if version_str != "unknown" else "0.0.0")

    def _supports(flag):
        if flag == "--reason":
            return version >= (5, 10, 0)
        if flag == "--printshellcmds":
            return version >= (5, 10, 0)
        if flag == "--latency-wait":
            return version >= (5, 10, 0)
        if flag == "--rerun-incomplete":
            return version >= (5, 8, 0)
        return True

    def _maybe_add(flag, value=None):
        if not flag:
            return
        if not _supports(flag):
            typer.echo(f"Warning: snakemake {version_str} does not support {flag}; skipping.")
            return
        if value is None:
            cmd.append(flag)
        else:
            cmd.extend([flag, str(value)])

    _maybe_add("--rerun-incomplete" if rerun_incomplete else None)
    _maybe_add("--printshellcmds" if printshellcmds else None)
    _maybe_add("--reason" if reason else None)
    if latency_wait:
        _maybe_add("--latency-wait", latency_wait)


def _write_run_manifest(outdir, cmd, resolved_cfg):
    run_dir = os.path.join(outdir, "run")
    os.makedirs(run_dir, exist_ok=True)

    with open(os.path.join(run_dir, "command.txt"), "w", encoding="utf-8") as handle:
        handle.write(" ".join(cmd) + "\n")

    with open(os.path.join(run_dir, "config_resolved.yaml"), "w", encoding="utf-8") as handle:
        yaml.safe_dump(resolved_cfg, handle, sort_keys=False)

    def _capture_version(argv):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True)
            output = (proc.stdout or proc.stderr).strip().splitlines()
            return output[0] if output else "unknown"
        except OSError:
            return "unknown"

    versions = {
        "python": _capture_version([sys.executable, "--version"]),
        "snakemake": _capture_version([sys.executable, "-m", "snakemake", "--version"]),
        "fastp": _capture_version(["fastp", "--version"]),
        "salmon": _capture_version(["salmon", "--version"]),
        "R": _capture_version(["Rscript", "--version"]),
    }
    with open(os.path.join(run_dir, "versions.tsv"), "w", encoding="utf-8") as handle:
        for key, value in versions.items():
            handle.write(f"{key}\t{value}\n")

    repo_root = Path(__file__).resolve().parent.parent
    git_rev = "unknown"
    if (repo_root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                git_rev = proc.stdout.strip()
        except (FileNotFoundError, subprocess.SubprocessError):
            git_rev = "unknown"
    with open(os.path.join(run_dir, "git_rev.txt"), "w", encoding="utf-8") as handle:
        handle.write(git_rev + "\n")


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
    input_base: str = typer.Option("", "--input-base", help="Optional prefix for FASTQ paths"),
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

    out_path = _abs_path(out)
    out_dir = out_path
    if not out_path.lower().endswith((".yaml", ".yml")):
        out_dir = out_path
        out_path = os.path.join(out_dir, "config.yaml")
    else:
        out_dir = os.path.dirname(out_path) or "."

    input_base = input_base.strip()
    if not input_base:
        input_base = "/input"
    input_base = input_base.rstrip("/\\")

    samples_path = os.path.join(out_dir, "metadata", "samples.tsv")
    os.makedirs(os.path.dirname(samples_path), exist_ok=True)
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
            fq1_path = fq1.strip()
            fq2_path = fq2.strip() if fq2 else ""
            if fq1_path and (":" in fq1_path or fq1_path.startswith("\\")):
                typer.echo("Warning: Windows-style path detected. Place files under /input and use relative paths.")
            if fq2_path and (":" in fq2_path or fq2_path.startswith("\\")):
                typer.echo("Warning: Windows-style path detected. Place files under /input and use relative paths.")
            row = [sample, conditions[sample], fq1_path]
            if paired:
                row.append(fq2_path)
            handle.write("\t".join(row) + "\n")

    outdir = out_dir

    ref_choice = typer.prompt(
        "Reference mode (fasta_gtf, preset, transcripts_only)",
        default="fasta_gtf",
    )
    ref_block = {}
    ref_preset = None
    ref_manifest = None
    if ref_choice == "preset":
        ref_preset = typer.prompt("Preset name (e.g. human_gencode)")
        ref_manifest = typer.prompt("Manifest path", default=str(Path("workflow") / "ref_manifest.yaml"))
        ref_cache = typer.prompt("Cache directory", default="refs_cache")
        typer.echo(
            "Run fetch explicitly: python -m app fetch --preset "
            f"{ref_preset} --release pinned --cache-dir {ref_cache}"
        )
    elif ref_choice == "transcripts_only":
        ref_block["transcripts_fasta"] = typer.prompt("Transcripts FASTA (.fa/.fa.gz)")
        if ":" in ref_block["transcripts_fasta"] or ref_block["transcripts_fasta"].startswith("\\"):
            typer.echo("Warning: Windows-style path detected. Place files under /input and use relative paths.")
    else:
        ref_block["transcripts_fasta"] = typer.prompt("Transcripts FASTA (.fa/.fa.gz)")
        ref_block["genome_fasta"] = typer.prompt("Genome FASTA (.fa/.fa.gz)")
        ref_block["gtf"] = typer.prompt("Annotation GTF (.gtf/.gtf.gz)")
        for key in ("transcripts_fasta", "genome_fasta", "gtf"):
            value = ref_block.get(key, "")
            if ":" in value or value.startswith("\\"):
                typer.echo("Warning: Windows-style path detected. Place files under /input and use relative paths.")

    contrasts_raw = typer.prompt("Contrasts (comma-separated A_vs_B, optional)", default="")
    contrasts = [item.strip() for item in contrasts_raw.split(",") if item.strip()]
    threads = typer.prompt("Threads", default="1")

    payload = {
        "engine": engine,
        "samples": sample_ids,
        "input": input_base,
        "output": outdir,
        "sample_table": samples_path,
        "ref": ref_block,
        "threads": int(threads),
    }
    if ref_preset:
        payload["ref_preset"] = ref_preset
    if ref_manifest:
        payload["ref_manifest"] = ref_manifest
    if contrasts:
        payload["contrasts"] = contrasts

    _write_yaml(payload, out_path)
    typer.echo(f"Wrote {out_path} and {samples_path}")


@app.command("validate")
def validate(
    config: str = typer.Option(..., "--config", help="Config YAML path"),
    input_dir: str = typer.Option(None, "--input", help="Input directory override"),
    output_dir: str = typer.Option(None, "--output", help="Output directory override"),
    skip_toolcheck: bool = typer.Option(False, "--skip-toolcheck", help="Skip checking tools in PATH"),
):
    cfg = _load_yaml(config)
    config_path = _abs_path(config)
    config_dir = os.path.dirname(config_path)
    indir = _abs_path(input_dir) if input_dir else _abs_path(cfg.get("input"))
    outdir = _abs_path(output_dir) if output_dir else _abs_path(cfg.get("output"))
    errors = []
    warnings = []

    engine = cfg.get("engine", "real")
    samples = cfg.get("samples") or []

    sample_table = cfg.get("sample_table")
    if sample_table:
        sample_table = _resolve_path(sample_table, indir, config_dir)
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
            _validate_paths([_resolve_path(p, indir, config_dir) for p in fastq1 if p], errors, "FASTQ")
            if any(fastq2):
                _validate_paths([_resolve_path(p, indir, config_dir) for p in fastq2 if p], errors, "FASTQ (R2)")
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
                _validate_paths([_resolve_path(fastq1[sample], indir, config_dir)], errors, "FASTQ")
            if fastq2 and sample in fastq2:
                _validate_paths([_resolve_path(fastq2[sample], indir, config_dir)], errors, "FASTQ (R2)")
            elif fastq2:
                warnings.append(f"Missing FASTQ2 for sample: {sample}")

    ref = cfg.get("ref") or {}
    transcripts = _resolve_path(ref.get("transcripts_fasta"), indir, config_dir)
    genome = _resolve_path(ref.get("genome_fasta"), indir, config_dir)
    gtf = _resolve_path(ref.get("gtf"), indir, config_dir)
    if engine == "real":
        if not transcripts:
            errors.append("transcripts_fasta is required for engine=real.")
    _validate_paths([p for p in (transcripts, genome, gtf) if p], errors, "reference")

    if not outdir:
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
    input_dir: str = typer.Option(None, "--input", help="Input directory"),
    output_dir: str = typer.Option(None, "--output", help="Output directory"),
    align: str = typer.Option("none", "--align", help="Alignment mode"),
    engine: str = typer.Option("", "--engine", help="Override engine"),
    threads: str = typer.Option("", "--threads", help="Override threads"),
    no_validate: bool = typer.Option(False, "--no-validate", help="Skip validation"),
    resume: bool = typer.Option(False, "--resume", help="Resume run (rerun incomplete)"),
    force: bool = typer.Option(False, "--force", help="Allow overwrite in non-empty output"),
    rerun_incomplete: bool = typer.Option(False, "--rerun-incomplete", help="Rerun incomplete jobs"),
    keep_going: bool = typer.Option(False, "--keep-going", help="Keep going after errors"),
    printshellcmds: bool = typer.Option(False, "--printshellcmds", help="Print shell commands"),
    reason: bool = typer.Option(False, "--reason", help="Print reason for each job"),
    latency_wait: int = typer.Option(60, "--latency-wait", help="Seconds to wait for filesystem latency"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Snakemake dry run (-n)"),
    forceall: bool = typer.Option(False, "--forceall", help="Force execution of all rules"),
    forcerun: str = typer.Option("", "--forcerun", help="Force execution of specific rule"),
    use_conda: bool = typer.Option(False, "--use-conda", help="Enable Snakemake conda integration"),
):
    cfg = _load_yaml(config)
    if not no_validate:
        validate(config=config, input_dir=input_dir, output_dir=output_dir, skip_toolcheck=False)

    final_input = input_dir or cfg.get("input") or "."
    final_output = output_dir or cfg.get("output") or "out"
    effective_engine = engine or cfg.get("engine", "real")

    if effective_engine == "real":
        if not final_output or final_output.strip() == "" or final_output == "/":
            typer.echo("Refusing to run: output directory is empty or root '/'.")
            raise typer.Exit(code=2)
        final_output_abs = _abs_path(final_output)
        if os.path.exists(final_output_abs):
            entries = [p for p in os.listdir(final_output_abs) if p not in (".", "..")]
            if entries and not (resume or force):
                typer.echo("Output directory is not empty; use --resume or --force to proceed.")
                raise typer.Exit(code=2)
        if resume:
            rerun_incomplete = True
    effective_threads = threads or str(cfg.get("threads") or "")
    args = RunArgs(
        input=_abs_path(final_input),
        output=_abs_path(final_output),
        config=_abs_path(config),
        align=align,
        engine=effective_engine,
        threads=effective_threads,
    )
    cmd = build_snakemake_cmd(args)
    if effective_engine == "real":
        if keep_going:
            cmd.append("--keep-going")
        _filter_snakemake_flags(cmd, reason, printshellcmds, latency_wait, rerun_incomplete)
        if dry_run:
            cmd.append("-n")
        if forceall:
            cmd.append("--forceall")
        if forcerun:
            cmd.extend(["--forcerun", forcerun])
        if use_conda:
            cmd.append("--use-conda")

        resolved_cfg = dict(cfg)
        resolved_cfg["input"] = _abs_path(final_input)
        resolved_cfg["output"] = _abs_path(final_output)
        resolved_cfg["align"] = align
        if engine:
            resolved_cfg["engine"] = engine
        if effective_threads:
            resolved_cfg["threads"] = int(effective_threads)
        resolved_cfg["use_conda"] = bool(use_conda)
        _write_run_manifest(_abs_path(final_output), cmd, resolved_cfg)
    typer.echo("Running: " + " ".join(cmd))
    raise typer.Exit(code=run_pipeline(args, cmd=cmd))


@app.command("snakemake-version")
def snakemake_version():
    typer.echo(_snakemake_version())


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
