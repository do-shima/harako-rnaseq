"""Single process and command-construction adapter for Snakemake."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass
class RunArgs:
    input: str
    output: str
    config: str
    align: str = "none"
    engine: str = ""
    threads: str = ""


def snakemake_workdir(output_dir: str) -> str:
    output_absolute = os.path.abspath(output_dir)
    root = os.environ.get("RNASEQ_SNAKEMAKE_WORKDIR_ROOT", "").strip()
    if root:
        root = os.path.abspath(os.path.expanduser(root))
    else:
        root = os.path.join(tempfile.gettempdir(), "rnaseq_pipeline_snakemake")
    digest = hashlib.sha256(output_absolute.encode("utf-8")).hexdigest()[:16]
    workdir = os.path.join(root, digest)
    os.makedirs(workdir, exist_ok=True)
    return workdir


def build_snakemake_cmd(args: RunArgs) -> list[str]:
    repository_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    snakefile = os.path.join(repository_root, "workflow", "Snakefile")
    workdir = snakemake_workdir(args.output) if args.engine == "real" else ""
    config_values = [
        f"input={os.path.abspath(args.input)}",
        f"output={os.path.abspath(args.output)}",
        f"align={args.align}",
    ]
    if args.engine:
        config_values.append(f"engine={args.engine}")
    if args.threads:
        config_values.append(f"threads={args.threads}")
    return [
        sys.executable,
        "-m",
        "snakemake",
        *(["--directory", workdir] if workdir else []),
        "-s",
        snakefile,
        "--configfile",
        args.config,
        "--config",
        *config_values,
        "--cores",
        str(args.threads or "1"),
    ]


def build_ui_snakemake_cmd(run_dir: Path, config_path: Path, threads: int) -> list[str]:
    return [
        "python",
        "-m",
        "snakemake",
        "--directory",
        str(snakemake_workdir(str(run_dir))),
        "-s",
        "workflow/Snakefile",
        "--configfile",
        str(config_path),
        "--config",
        "input=/input",
        f"output={run_dir}",
        "--cores",
        str(int(threads)),
        "-p",
        "--show-failed-logs",
        "--latency-wait",
        "60",
    ]


def run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True)


def snakemake_version_text() -> str:
    try:
        process = run_capture(["python", "-m", "snakemake", "--version"])
    except Exception:
        return "unknown"
    text = (process.stdout or process.stderr or "").strip()
    return text.splitlines()[0].strip() if text else "unknown"


def run_pipeline(
    args: RunArgs,
    cmd: list[str] | None = None,
    output_stream: TextIO | None = None,
) -> int:
    command = cmd or build_snakemake_cmd(args)
    print("Running:", " ".join(command), file=output_stream or sys.stdout)
    if output_stream is None:
        result = subprocess.run(command)
    else:
        result = subprocess.run(command, stdout=output_stream, stderr=output_stream)
    return result.returncode
