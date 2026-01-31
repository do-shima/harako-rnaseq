import argparse
import os
import subprocess
import sys


def parse_args():
    parser = argparse.ArgumentParser(description="RNA-seq pipeline entrypoint")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the pipeline")
    run_p.add_argument("--input", required=True, help="Input directory")
    run_p.add_argument("--output", required=True, help="Output directory")
    run_p.add_argument("--config", required=True, help="Config YAML file")
    run_p.add_argument("--align", default="none", choices=["none", "star", "hisat2"], help="Alignment mode")

    return parser.parse_args()


def run_pipeline(args):
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
        "1",
    ]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd)
    return result.returncode


def main():
    args = parse_args()
    if args.command == "run":
        raise SystemExit(run_pipeline(args))


if __name__ == "__main__":
    main()