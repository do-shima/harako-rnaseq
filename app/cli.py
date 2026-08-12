import os
import re
import shutil
import subprocess
import sys
import json
import hashlib
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

import typer
import yaml

from .run import RunArgs, build_snakemake_cmd, run_pipeline
from .analysis_eligibility import (
    AnalysisPlanError,
    analysis_plan_from_rows,
    assert_analysis_plan_consistent,
    evaluate_analysis_eligibility,
    resolve_analysis_plan,
)
from .reference_presets import (
    ReferencePresetError,
    build_reference_provenance,
    resolve_existing_cache_paths,
    resolve_preset_release,
    validate_builtin_manifest,
)
from .version import VERSION
from .agent_cli import agent_app


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(VERSION)
        raise typer.Exit()


app = typer.Typer(help="RNA-seq pipeline CLI")
FASTQ_EXTS = (".fastq", ".fastq.gz", ".fq", ".fq.gz")
SAMPLE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

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


def _scan_fastq(root: str):
    files = []
    if not root or not os.path.isdir(root):
        return files
    for path in Path(root).rglob("*"):
        if path.is_file() and path.name.lower().endswith(FASTQ_EXTS):
            files.append(str(path))
    return files


def _warn_fastq_extensions(paths, warnings):
    for path in paths:
        if path and not path.lower().endswith(FASTQ_EXTS):
            warnings.append(f"FASTQ file has unexpected extension: {path}")


def _warn_duplicate_fastq(paths, warnings):
    counts = Counter([p for p in paths if p])
    duplicates = [p for p, count in counts.items() if count > 1]
    if duplicates:
        warnings.append(f"Duplicate FASTQ paths detected: {', '.join(duplicates)}")


def _warn_sample_names(samples, warnings):
    for sample in samples:
        if not sample:
            continue
        if not SAMPLE_NAME_RE.match(sample):
            warnings.append(
                f"Sample name '{sample}' contains spaces/special chars. "
                "Use letters, numbers, dot, underscore, or dash."
            )


def _contrast_levels_from_samples(rows):
    levels = []
    seen = set()
    for row in rows:
        cond = row.get("condition") or ""
        if cond and cond not in seen:
            levels.append(cond)
            seen.add(cond)
    return levels


def _canonical_pair(a, b):
    return f"{a}_vs_{b}"


def _resolve_contrasts(cfg, sample_rows):
    eligibility = evaluate_analysis_eligibility(sample_rows)
    levels = _contrast_levels_from_samples(sample_rows)
    mode = cfg.get("contrast_mode")
    legacy = cfg.get("contrasts") or []
    if not mode:
        if legacy:
            mode = "legacy"
        elif levels:
            mode = "ref"
        else:
            mode = "legacy"
    resolved_pairs = []
    if not eligibility.eligible_for_de:
        return {
            "mode": mode,
            "levels": levels,
            "ref": cfg.get("contrast_ref"),
            "pairs": [],
            "generated": [],
        }

    if mode == "ref":
        ref = cfg.get("contrast_ref")
        if not ref and levels:
            ref = levels[0]
        if ref:
            for lvl in levels:
                if lvl != ref:
                    resolved_pairs.append((lvl, ref))
    elif mode == "pairwise":
        for i in range(len(levels)):
            for j in range(i + 1, len(levels)):
                a, b = levels[i], levels[j]
                resolved_pairs.append((a, b))
    elif mode == "select":
        pairs = cfg.get("contrast_pairs") or []
        for pair in pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                resolved_pairs.append((pair[0], pair[1]))
    else:
        for item in legacy:
            if "_vs_" in item:
                left, right = item.split("_vs_", 1)
                resolved_pairs.append((left, right))

    generated = [_canonical_pair(a, b) for a, b in resolved_pairs]
    return {
        "mode": mode,
        "levels": levels,
        "ref": cfg.get("contrast_ref"),
        "pairs": resolved_pairs,
        "generated": generated,
    }


def _validate_paths(paths, errors, label):
    for path in paths:
        if path and not os.path.exists(path):
            errors.append(f"Missing {label} file: {path}")


def _check_output_writable(outdir: str, errors):
    if not outdir:
        return
    try:
        os.makedirs(outdir, exist_ok=True)
        if os.path.exists(outdir) and not os.path.isdir(outdir):
            errors.append(f"Output path is not a directory: {outdir}")
            return
        test_path = os.path.join(outdir, ".validate_write_test")
        with open(test_path, "w", encoding="utf-8") as handle:
            handle.write("ok\n")
        os.remove(test_path)
    except Exception as exc:
        errors.append(f"Output directory is not writable: {outdir} ({exc})")


def _validate_contrasts(cfg, sample_rows, engine, errors, warnings, eligibility=None):
    eligibility = eligibility or evaluate_analysis_eligibility(sample_rows)
    levels = _contrast_levels_from_samples(sample_rows)
    if not eligibility.structurally_valid:
        return
    if not eligibility.eligible_for_de:
        warnings.append(
            f"Analysis mode is qc_only ({eligibility.reason_code}); contrasts are "
            "retained as requested settings but are not applied."
        )
        return

    mode = cfg.get("contrast_mode")
    legacy = cfg.get("contrasts") or []
    if mode == "legacy" or legacy:
        errors.append(
            "Legacy contrasts are not supported. "
            "Use contrast_mode=ref|pairwise|select with contrast_ref or contrast_pairs."
        )
        return
    if mode == "ref":
        ref = cfg.get("contrast_ref")
        if not ref:
            errors.append("contrast_ref is required when contrast_mode=ref.")
        elif ref not in levels:
            errors.append(f"contrast_ref '{ref}' not in detected levels {levels}.")
        if len(levels) < 2:
            errors.append("contrast_mode=ref requires at least two condition levels.")
    elif not mode and levels:
        ref = cfg.get("contrast_ref")
        if ref and ref not in levels:
            errors.append(f"contrast_ref '{ref}' not in detected levels {levels}.")
        if not ref and len(levels) >= 2:
            warnings.append(f"contrast_mode not set; defaulting to ref using {levels[0]}.")
    elif mode == "pairwise":
        if len(levels) < 2:
            errors.append("contrast_mode=pairwise requires at least two condition levels.")
    elif mode == "select":
        pairs = cfg.get("contrast_pairs") or []
        if not pairs:
            errors.append("contrast_mode=select requires contrast_pairs.")
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                errors.append(f"Invalid contrast pair: {pair} (expected [A, B]).")
                continue
            left, right = pair[0], pair[1]
            if left == right:
                errors.append(f"Invalid contrast pair: {left}_vs_{right} (A and B must differ).")
            if left not in levels or right not in levels:
                errors.append(f"Invalid contrast pair: {left}_vs_{right} (levels={levels}).")


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


def _filter_snakemake_flags(cmd, printshellcmds, latency_wait, rerun_incomplete, quiet_categories=None):
    version_str = _snakemake_version()
    version = _parse_version(version_str if version_str != "unknown" else "0.0.0")
    quiet_categories = [str(item) for item in (quiet_categories or []) if str(item).strip()]

    def _supports(flag):
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
    if latency_wait:
        _maybe_add("--latency-wait", latency_wait)
    if quiet_categories:
        _maybe_add("--quiet")
        cmd.extend(quiet_categories)


def _git_rev():
    repo_root = Path(__file__).resolve().parent.parent
    if not (repo_root / ".git").exists():
        return "unknown"
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return "unknown"
        rev = proc.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if dirty.returncode == 0 and (dirty.stdout or "").strip():
            rev += "+dirty"
        return rev
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"


def _sha256_path(path: str):
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_manifest_payload(config_path: str, resolved_cfg: dict):
    run_id_provenance = dict(resolved_cfg.get("reference_provenance") or {})
    run_id_provenance.pop("requested_preset", None)
    payload = {
        "schema_version": 1,
        "config_sha256": _sha256_path(config_path),
        "samples_sha256": "",
        "input": resolved_cfg.get("input"),
        "engine": resolved_cfg.get("engine"),
        "threads": resolved_cfg.get("threads"),
        "align": resolved_cfg.get("align"),
        "species": resolved_cfg.get("species"),
        "ref": resolved_cfg.get("ref"),
        "ref_preset": resolved_cfg.get("ref_preset"),
        "ref_release": resolved_cfg.get("ref_release"),
        "ref_manifest": resolved_cfg.get("ref_manifest"),
        "reference_provenance": run_id_provenance or None,
        "analysis_plan": resolved_cfg.get("analysis_plan"),
        "contrast_mode": resolved_cfg.get("contrast_mode"),
        "contrast_ref": resolved_cfg.get("contrast_ref"),
        "contrast_pairs": resolved_cfg.get("contrast_pairs"),
        "contrasts": resolved_cfg.get("contrasts"),
        "enrichment": resolved_cfg.get("enrichment"),
        "git_rev": _git_rev(),
    }
    sample_table = resolved_cfg.get("sample_table")
    if sample_table:
        payload["samples_sha256"] = _sha256_path(sample_table)
    return payload


def _manifest_run_id(payload: dict):
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_manifest_json(run_dir: str, payload: dict, run_id: str):
    manifest = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    path = os.path.join(run_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)


def _write_run_manifest(outdir, cmd, resolved_cfg, config_path: str, run_id_override: str = ""):
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
    ref_cfg = resolved_cfg.get("ref") if isinstance(resolved_cfg, dict) else {}
    if isinstance(ref_cfg, dict):
        for key in ("transcripts_fasta", "genome_fasta", "gtf"):
            ref_path = ref_cfg.get(key)
            if not ref_path:
                continue
            path_obj = Path(ref_path)
            if path_obj.exists() and path_obj.is_file():
                import hashlib

                digest = hashlib.sha256()
                with path_obj.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                versions[f"ref.{key}.sha256"] = digest.hexdigest()
            else:
                versions[f"ref.{key}.sha256"] = "missing"
    os_release_path = Path("/etc/os-release")
    if os_release_path.exists():
        versions["os_release"] = os_release_path.read_text(encoding="utf-8", errors="ignore").replace("\n", "\\n")
    else:
        versions["os_release"] = "missing"
    with open(os.path.join(run_dir, "versions.tsv"), "w", encoding="utf-8") as handle:
        handle.write("key\tvalue\n")
        for key, value in versions.items():
            handle.write(f"{key}\t{value}\n")

    with open(os.path.join(run_dir, "pip_freeze.txt"), "w", encoding="utf-8") as handle:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True,
                text=True,
                check=False,
            )
            handle.write(proc.stdout or proc.stderr or "unavailable\n")
        except OSError as exc:
            handle.write(f"missing ({exc})\n")

    with open(os.path.join(run_dir, "sessionInfo.txt"), "w", encoding="utf-8") as handle:
        try:
            proc = subprocess.run(
                ["Rscript", "-e", "sessionInfo()"],
                capture_output=True,
                text=True,
                check=False,
            )
            handle.write(proc.stdout or proc.stderr or "unavailable\n")
        except OSError as exc:
            handle.write(f"missing ({exc})\n")

    git_rev = _git_rev()
    with open(os.path.join(run_dir, "git_rev.txt"), "w", encoding="utf-8") as handle:
        handle.write(git_rev + "\n")

    manifest_payload = _build_manifest_payload(config_path, resolved_cfg)
    computed_run_id = _manifest_run_id(manifest_payload)
    run_id = run_id_override or computed_run_id
    if run_id_override and run_id_override != computed_run_id:
        typer.echo(f"Warning: provided run_id {run_id_override} != computed {computed_run_id}")
    _write_manifest_json(run_dir, manifest_payload, run_id)


def _resolve_fastq_from_config(cfg: dict):
    fastq = cfg.get("fastq") or {}
    fastq1 = cfg.get("fastq1") or {}
    fastq2 = cfg.get("fastq2") or {}
    if fastq1 or fastq2:
        return fastq1, fastq2
    return fastq, {}


def _resolve_run_cfg(cfg: dict, config_path: str, final_input: str, final_output: str, align: str, engine: str, threads: str, use_conda: bool):
    resolved_cfg = dict(cfg)
    resolved_cfg["input"] = _abs_path(final_input) if final_input else ""
    resolved_cfg["output"] = _abs_path(final_output) if final_output else ""
    resolved_cfg["align"] = align
    if engine:
        resolved_cfg["engine"] = engine
    if threads:
        resolved_cfg["threads"] = int(threads)
    resolved_cfg["use_conda"] = bool(use_conda)
    config_dir = os.path.dirname(_abs_path(config_path)) if config_path else ""
    if "sample_table" in resolved_cfg:
        resolved_cfg["sample_table"] = _resolve_path(resolved_cfg["sample_table"], resolved_cfg.get("input"), config_dir)
        try:
            rows = _parse_sample_table(resolved_cfg["sample_table"])
            config_path_obj = Path(config_path)
            legacy_frozen = (
                config_path_obj.name == "config_resolved.yaml"
                and config_path_obj.parent.name == "run"
            )
            plan, _ = resolve_analysis_plan(
                resolved_cfg.get("analysis_plan"),
                rows,
                legacy_frozen=legacy_frozen,
            )
            resolved_cfg["analysis_plan"] = plan
            resolved_cfg["contrast_resolved"] = _resolve_contrasts(resolved_cfg, rows)
            if not resolved_cfg["analysis_plan"]["eligible_for_de"]:
                enrichment = dict(resolved_cfg.get("enrichment") or {})
                if enrichment:
                    enrichment["enable"] = False
                    resolved_cfg["enrichment"] = enrichment
        except OSError:
            pass
    resolved_cfg = _resolve_reference_cfg(resolved_cfg, config_path)
    return resolved_cfg


def _resolve_reference_cfg(cfg: dict, config_path: str) -> dict:
    resolved = dict(cfg)
    preset = resolved.get("ref_preset")
    if not preset:
        return resolved
    # Frozen configs with explicit paths remain authoritative.
    ref = resolved.get("ref")
    species = str(resolved.get("species") or "").lower()
    explicit = ref if isinstance(ref, dict) else {}
    if species and isinstance(explicit.get(species), dict):
        explicit = explicit[species]
    if isinstance(explicit, dict) and explicit.get("transcripts_fasta"):
        return resolved
    manifest_path = resolved.get("ref_manifest") or str(
        Path(__file__).resolve().parents[1] / "workflow" / "ref_manifest.yaml"
    )
    manifest_path = Path(manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = Path(config_path).resolve().parent / manifest_path
    manifest = _load_yaml(manifest_path)
    validate_builtin_manifest(manifest)
    requested_release = resolved.get("ref_release", "pinned")
    canonical, release = resolve_preset_release(manifest, preset, requested_release)
    cache_root = Path(
        resolved.get("ref_cache_dir")
        or Path(resolved.get("output") or ".") / "refs_cache"
    )
    if not cache_root.is_absolute():
        cache_root = Path(config_path).resolve().parent / cache_root
    cache = resolve_existing_cache_paths(
        manifest, cache_root, preset, requested_release
    )
    if cache:
        raw_paths = cache["paths"]
        paths = {
            "transcripts_fasta": str(raw_paths["transcripts_fasta_url"]),
            "genome_fasta": str(raw_paths["genome_fasta_url"]),
            "gtf": str(raw_paths["gtf_url"]),
        }
        verified = bool(cache["verified"])
        cache_source = cache["cache_source"]
    else:
        base = cache_root / canonical / release
        paths = {
            "transcripts_fasta": str(base / "transcripts.fa.gz"),
            "genome_fasta": str(base / "genome.fa.gz"),
            "gtf": str(base / "annotation.gtf.gz"),
        }
        verified = False
        cache_source = "canonical"
    resolved["ref_preset"] = canonical
    resolved["ref_release"] = release
    resolved["ref"] = {species: paths}
    resolved["reference_provenance"] = build_reference_provenance(
        manifest,
        preset,
        requested_release,
        paths=paths,
        checksum_verified=verified,
        cache_source=cache_source,
    )
    return resolved


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
        ref_preset = typer.prompt("Preset name (e.g. human_ensembl_grch38)")
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

    contrast_mode = typer.prompt("Contrast mode (ref, pairwise, select, legacy)", default="ref")
    contrast_ref = None
    contrast_pairs = []
    contrasts = []
    condition_levels = list(dict.fromkeys(conditions.values()))

    if contrast_mode == "ref":
        default_ref = condition_levels[0] if condition_levels else ""
        contrast_ref = typer.prompt("Reference condition", default=default_ref)
    elif contrast_mode == "pairwise":
        pass
    elif contrast_mode == "select":
        typer.echo("Enter contrast pairs as A,B (empty to finish).")
        while True:
            raw = typer.prompt("Pair", default="")
            if not raw:
                break
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if len(parts) != 2:
                typer.echo("Provide exactly two condition names separated by a comma.")
                continue
            contrast_pairs.append(parts)
    else:
        contrasts_raw = typer.prompt("Legacy contrasts (comma-separated A_vs_B)", default="")
        contrasts = [item.strip() for item in contrasts_raw.split(",") if item.strip()]
    threads = typer.prompt("Threads", default="1")
    enable_advanced = typer.confirm("Advanced options?", default=False)

    enrichment_cfg = None
    if enable_advanced:
        enable_enrichment = typer.confirm("Enable enrichment?", default=False)
        if enable_enrichment:
            methods_raw = typer.prompt("Enrichment methods (comma-separated ORA,GSEA)", default="ORA,GSEA")
            methods = [item.strip().upper() for item in methods_raw.split(",") if item.strip()]
            alpha = float(typer.prompt("Enrichment alpha (FDR)", default="0.05"))
            lfc = float(typer.prompt("Enrichment min abs(log2FC)", default="0"))
            top_terms = int(typer.prompt("Top terms to show", default="15"))
            rank_metric = typer.prompt("Rank metric (stat)", default="stat")
            enrichment_cfg = {
                "enable": True,
                "methods": methods or ["ORA", "GSEA"],
                "alpha": alpha,
                "lfc": lfc,
                "top_terms": top_terms,
                "rank_metric": rank_metric,
            }

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
    if contrast_mode:
        payload["contrast_mode"] = contrast_mode
    if contrast_ref:
        payload["contrast_ref"] = contrast_ref
    if contrast_pairs:
        payload["contrast_pairs"] = contrast_pairs
    if enrichment_cfg:
        payload["enrichment"] = enrichment_cfg

    init_rows = [
        {"sample": sample, "condition": conditions.get(sample, "")}
        for sample in sample_ids
    ]
    payload["analysis_plan"] = analysis_plan_from_rows(init_rows)
    if not payload["analysis_plan"]["eligible_for_de"]:
        payload["requested_analysis_options"] = {
            "contrast_mode": payload.pop("contrast_mode", None),
            "contrast_ref": payload.pop("contrast_ref", None),
            "contrast_pairs": payload.pop("contrast_pairs", None),
            "contrasts": payload.pop("contrasts", None),
            "enrichment": payload.pop("enrichment", None),
        }

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
    reference_resolution_error = None
    try:
        validation_cfg = dict(cfg)
        if output_dir:
            validation_cfg["output"] = _abs_path(output_dir)
        cfg = _resolve_reference_cfg(validation_cfg, config_path)
    except (ReferencePresetError, OSError, yaml.YAMLError) as exc:
        reference_resolution_error = str(exc)
    config_dir = os.path.dirname(config_path)
    indir = _abs_path(input_dir) if input_dir else _abs_path(cfg.get("input"))
    outdir = _abs_path(output_dir) if output_dir else _abs_path(cfg.get("output"))
    errors = []
    warnings = []
    if reference_resolution_error:
        errors.append(reference_resolution_error)

    engine = cfg.get("engine", "real")
    samples = cfg.get("samples") or []
    sample_rows = []

    if indir and not _scan_fastq(indir):
        errors.append(
            f"No FASTQ files found under input: {indir}. "
            "Hint: mount FASTQ files under /input (e.g. -v <host>:/input:ro)."
        )

    sample_table = cfg.get("sample_table")
    if sample_table:
        sample_table = _resolve_path(sample_table, indir, config_dir)
        if not os.path.exists(sample_table):
            errors.append(f"Sample table not found: {sample_table}")
        else:
            rows = _parse_sample_table(sample_table)
            sample_rows = rows
            samples = [row.get("sample") for row in rows if row.get("sample")]
            if not samples:
                errors.append("Sample table has no samples.")
            conditions = [row.get("condition") for row in rows if row.get("condition")]
            fastq1 = [row.get("fastq1") for row in rows]
            fastq2 = [row.get("fastq2") for row in rows]
            for idx, row in enumerate(rows, start=2):
                sample_id = row.get("sample")
                if not sample_id:
                    errors.append(f"Sample table row {idx}: missing sample value.")
                if not row.get("condition"):
                    errors.append(f"Sample table row {idx}: missing condition for sample {sample_id or '(blank)'}")
                if not row.get("fastq1"):
                    errors.append(f"Sample table row {idx}: missing fastq1 for sample {sample_id or '(blank)'}")
            resolved_fastq1 = [_resolve_path(p, indir, config_dir) for p in fastq1 if p]
            resolved_fastq2 = [_resolve_path(p, indir, config_dir) for p in fastq2 if p]
            _validate_paths(resolved_fastq1, errors, "FASTQ")
            if any(fastq2):
                _validate_paths(resolved_fastq2, errors, "FASTQ (R2)")
                if not all(fastq2):
                    warnings.append("Paired-end FASTQ2 missing for some samples.")
            for idx, row in enumerate(rows):
                if row.get("fastq2") and not row.get("fastq1"):
                    errors.append(f"Sample {row.get('sample') or idx} has FASTQ2 but no FASTQ1.")
            _warn_fastq_extensions(resolved_fastq1 + resolved_fastq2, warnings)
            _warn_duplicate_fastq(resolved_fastq1 + resolved_fastq2, warnings)
            _warn_sample_names(samples, warnings)
    else:
        if not samples:
            errors.append("No samples defined in config.")
        conditions = cfg.get("conditions") or {}
        sample_rows = [{"sample": sample, "condition": conditions.get(sample, "")} for sample in samples]
        if engine == "real":
            missing_conditions = [s for s in samples if not conditions.get(s)]
            if missing_conditions:
                errors.append(
                    "Missing condition for sample(s): " + ", ".join(missing_conditions)
                )
        fastq1, fastq2 = _resolve_fastq_from_config(cfg)
        resolved_fastq1 = []
        resolved_fastq2 = []
        for sample in samples:
            if sample not in fastq1:
                errors.append(f"Missing FASTQ for sample: {sample}")
            else:
                resolved = _resolve_path(fastq1[sample], indir, config_dir)
                resolved_fastq1.append(resolved)
                _validate_paths([resolved], errors, "FASTQ")
            if fastq2 and sample in fastq2:
                resolved = _resolve_path(fastq2[sample], indir, config_dir)
                resolved_fastq2.append(resolved)
                _validate_paths([resolved], errors, "FASTQ (R2)")
            elif fastq2:
                warnings.append(f"Missing FASTQ2 for sample: {sample}")
        _warn_fastq_extensions(resolved_fastq1 + resolved_fastq2, warnings)
        _warn_duplicate_fastq(resolved_fastq1 + resolved_fastq2, warnings)
        _warn_sample_names(samples, warnings)

    eligibility = evaluate_analysis_eligibility(sample_rows)
    structural_messages = {
        "no_samples": "No samples are available for analysis.",
        "missing_sample": "Sample table contains an empty sample identifier.",
        "missing_condition": "Sample table contains an empty condition.",
        "duplicate_sample": "Sample table contains a duplicate sample identifier.",
    }
    if not eligibility.structurally_valid:
        message = structural_messages.get(eligibility.reason_code)
        if message and message not in errors:
            errors.append(message)
    configured_plan = cfg.get("analysis_plan")
    if configured_plan:
        try:
            assert_analysis_plan_consistent(configured_plan, sample_rows)
        except AnalysisPlanError as exc:
            errors.append(str(exc))

    _validate_contrasts(cfg, sample_rows, engine, errors, warnings, eligibility)

    ref = cfg.get("ref") or {}
    species = (cfg.get("species") or "").strip().lower()
    ref_species = {}
    if isinstance(ref, dict) and species and isinstance(ref.get(species), dict):
        ref_species = ref.get(species) or {}
    ref_preset = cfg.get("ref_preset")
    if "ref_preset" in cfg and not ref_preset:
        errors.append("ref_preset is empty. Set ref_preset or provide explicit ref paths.")
    transcripts = _resolve_path(ref.get("transcripts_fasta") or ref_species.get("transcripts_fasta"), indir, config_dir)
    genome = _resolve_path(ref.get("genome_fasta") or ref_species.get("genome_fasta"), indir, config_dir)
    gtf = _resolve_path(ref.get("gtf") or ref_species.get("gtf"), indir, config_dir)
    if ref_preset:
        refs_present = [p for p in (transcripts, genome, gtf) if p]
        _validate_paths(refs_present, errors, "reference")
        provenance = cfg.get("reference_provenance") or {}
        if not provenance.get("checksum_verified"):
            warnings.append(
                f"Built-in reference {ref_preset}/{cfg.get('ref_release')} is not checksum-verified."
            )
    else:
        if transcripts and not (genome or gtf):
            if not transcripts:
                errors.append("transcripts_fasta is required for transcripts-only mode.")
        else:
            missing = [name for name, val in [("transcripts_fasta", transcripts),
                                              ("genome_fasta", genome),
                                              ("gtf", gtf)] if not val]
            if missing:
                errors.append("Missing reference field(s): " + ", ".join(missing))
        if engine == "real" and not transcripts:
            errors.append("transcripts_fasta is required for engine=real.")
        refs_present = [p for p in (transcripts, genome, gtf) if p]
        _validate_paths(refs_present, errors, "reference")
        if any(err.startswith("Missing reference file:") for err in errors):
            errors.append(
                "Hint: place reference files under /input (e.g. /input/refs/...) "
                "or set ref paths relative to --input."
            )

    enrichment = cfg.get("enrichment") or {}
    if enrichment.get("enable"):
        methods = enrichment.get("methods") or ["ORA", "GSEA"]
        methods = [str(m).upper() for m in methods]
        invalid = [m for m in methods if m not in ("ORA", "GSEA")]
        if invalid:
            errors.append(f"Invalid enrichment methods: {', '.join(invalid)} (allowed: ORA, GSEA)")
        rank_metric = enrichment.get("rank_metric", "stat")
        if "GSEA" in methods and rank_metric != "stat":
            warnings.append("GSEA rank_metric should be 'stat' for DESeq2 results.")
        species = cfg.get("species", "mouse")
        if species not in ("human", "mouse", "rat"):
            warnings.append(
                "Enrichment enabled for unsupported species; orgdb may be missing and runs will be skipped."
            )
        if not eligibility.enrichment_allowed:
            warnings.append(
                "Enrichment is disabled because inferential differential-expression "
                "results are unavailable in QC-only mode."
            )

    if not outdir:
        warnings.append("No output directory set; run uses --output.")

    if outdir:
        parent = outdir if os.path.exists(outdir) else os.path.dirname(outdir)
        if parent and not os.access(parent, os.W_OK):
            errors.append(f"Output directory is not writable: {outdir}")
        _check_output_writable(outdir, errors)

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

    typer.echo(f"Analysis mode: {eligibility.mode}")
    typer.echo(f"Reason code: {eligibility.reason_code}")
    typer.echo(
        "Condition counts: "
        + (
            ", ".join(
                f"{condition}={count}"
                for condition, count in eligibility.condition_counts.items()
            )
            or "none"
        )
    )
    typer.echo(f"Total samples: {eligibility.total_samples}")
    typer.echo("Validation OK.")


def _run_impl(
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
    output_stream=None,
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
        quiet_categories = []
        if quiet_reason or not reason:
            quiet_categories.append("reason")
        _filter_snakemake_flags(cmd, printshellcmds, latency_wait, rerun_incomplete, quiet_categories=quiet_categories)
        if dry_run:
            cmd.append("-n")
        if forceall:
            cmd.append("--forceall")
        if forcerun:
            cmd.extend(["--forcerun", forcerun])
        if use_conda:
            cmd.append("--use-conda")

        resolved_cfg = _resolve_run_cfg(
            cfg,
            config,
            final_input,
            final_output,
            align,
            engine or effective_engine,
            effective_threads,
            use_conda,
        )
        _write_run_manifest(_abs_path(final_output), cmd, resolved_cfg, config, run_id_override=run_id)
    typer.echo("Running: " + " ".join(cmd))
    return run_pipeline(args, cmd=cmd, output_stream=output_stream)


@app.command("run")
def run(
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
):
    raise typer.Exit(
        code=_run_impl(
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


@app.command("run-id")
def run_id_cmd(
    config: str = typer.Option(..., "--config", help="Config YAML path"),
    input_dir: str = typer.Option(None, "--input", help="Input directory"),
    output_dir: str = typer.Option(None, "--output", help="Output directory (optional; excluded from hash)"),
    align: str = typer.Option("none", "--align", help="Alignment mode"),
    engine: str = typer.Option("", "--engine", help="Override engine"),
    threads: str = typer.Option("", "--threads", help="Override threads"),
    use_conda: bool = typer.Option(False, "--use-conda", help="Enable Snakemake conda integration"),
):
    cfg = _load_yaml(config)
    final_input = input_dir or cfg.get("input") or "."
    final_output = output_dir or cfg.get("output") or ""
    resolved_cfg = _resolve_run_cfg(
        cfg,
        config,
        final_input,
        final_output,
        align,
        engine or cfg.get("engine", ""),
        threads or str(cfg.get("threads") or ""),
        use_conda,
    )
    payload = _build_manifest_payload(config, resolved_cfg)
    run_id = _manifest_run_id(payload)
    typer.echo(run_id)


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
