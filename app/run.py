import os
import subprocess
import sys
import tempfile
import hashlib
from dataclasses import dataclass


@dataclass
class RunArgs:
    input: str
    output: str
    config: str
    align: str = "none"
    engine: str = ""
    threads: str = ""


def snakemake_workdir(output_dir: str):
    output_abs = os.path.abspath(output_dir)
    root = os.environ.get("RNASEQ_SNAKEMAKE_WORKDIR_ROOT", "").strip()
    if root:
        root = os.path.abspath(os.path.expanduser(root))
    else:
        root = os.path.join(tempfile.gettempdir(), "rnaseq_pipeline_snakemake")
    digest = hashlib.sha256(output_abs.encode("utf-8")).hexdigest()[:16]
    workdir = os.path.join(root, digest)
    os.makedirs(workdir, exist_ok=True)
    return workdir


def build_snakemake_cmd(args: RunArgs):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    snakefile = os.path.join(repo_root, "workflow", "Snakefile")
    workdir = snakemake_workdir(args.output) if args.engine == "real" else ""

    config_kv = [
        f"input={os.path.abspath(args.input)}",
        f"output={os.path.abspath(args.output)}",
        f"align={args.align}",
    ]
    if args.engine:
        config_kv.append(f"engine={args.engine}")
    if args.threads:
        config_kv.append(f"threads={args.threads}")

    cmd = [
        sys.executable,
        "-m",
        "snakemake",
        *(["--directory", workdir] if workdir else []),
        "-s",
        snakefile,
        "--configfile",
        args.config,
        "--config",
        *config_kv,
        "--cores",
        str(args.threads or "1"),
    ]
    return cmd


def run_pipeline(args: RunArgs, cmd=None, output_stream=None):
    cmd = cmd or build_snakemake_cmd(args)
    print("Running:", " ".join(cmd), file=output_stream or sys.stdout)
    if output_stream is None:
        result = subprocess.run(cmd)
    else:
        result = subprocess.run(cmd, stdout=output_stream, stderr=output_stream)
    return result.returncode
