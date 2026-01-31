import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class RunArgs:
    input: str
    output: str
    config: str
    align: str = "none"
    engine: str = ""
    threads: str = ""


def build_snakemake_cmd(args: RunArgs):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    snakefile = os.path.join(repo_root, "workflow", "Snakefile")

    cmd = [
        sys.executable,
        "-m",
        "snakemake",
        "-s",
        snakefile,
        "--configfile",
        args.config,
        "--config",
        f"input={os.path.abspath(args.input)}",
        f"output={os.path.abspath(args.output)}",
        f"align={args.align}",
        "--cores",
        str(args.threads or "1"),
    ]
    if args.engine:
        cmd.extend(["--config", f"engine={args.engine}"])
    if args.threads:
        cmd.extend(["--config", f"threads={args.threads}"])
    return cmd


def run_pipeline(args: RunArgs, cmd=None):
    cmd = cmd or build_snakemake_cmd(args)
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd)
    return result.returncode
