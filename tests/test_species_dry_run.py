import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def _write_yaml(path: Path, payload: dict):
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_samples(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("sample\tcondition\tfastq1\nsample1\tA\tsample1.fastq\n", encoding="utf-8")


def main():
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "tests" / "data"
    snakefile = repo_root / "workflow" / "Snakefile"

    for species in ("mouse", "rat", "human"):
        out_dir = repo_root / f"out_smoke_{species}"
        if out_dir.exists():
            shutil.rmtree(out_dir)
        samples_path = out_dir / "metadata" / "samples.tsv"
        _write_samples(samples_path)

        cfg = {
            "engine": "stub",
            "species": species,
            "samples": ["sample1"],
            "input": str(data_dir),
            "output": str(out_dir),
            "sample_table": str(samples_path),
            "ref": {
                "transcripts_fasta": "transcripts.fa",
                "genome_fasta": "genome.fa",
                "gtf": "genes.gtf",
            },
        }
        _write_yaml(out_dir / "config.yaml", cfg)

        validate_cmd = [
            sys.executable,
            "-m",
            "app",
            "validate",
            "--config",
            str(out_dir / "config.yaml"),
            "--input",
            str(data_dir),
            "--output",
            str(out_dir),
        ]
        validate = subprocess.run(validate_cmd, capture_output=True, text=True)
        validate_out = (validate.stdout or "") + ("\n" + validate.stderr if validate.stderr else "")
        if validate.returncode != 0:
            raise SystemExit(f"{species} validate failed:\n{validate_out}")

        cmd = [
            sys.executable,
            "-m",
            "snakemake",
            "--directory",
            str(out_dir),
            "-s",
            str(snakefile),
            "--configfile",
            str(out_dir / "config.yaml"),
            "--config",
            f"input={data_dir}",
            f"output={out_dir}",
            "--cores",
            "1",
            "-n",
            "-p",
            "--",
            "report",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        if proc.returncode != 0:
            raise SystemExit(f"{species} dry-run failed:\n{output}")
        if f"[refs] species={species}" not in output:
            raise SystemExit(f"{species} dry-run missing refs line:\n{output}")


if __name__ == "__main__":
    main()
